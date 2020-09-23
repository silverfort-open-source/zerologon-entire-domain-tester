# Silverfort's Scanner for Vulnerable DCs with Zerologon
This tool scans your entire domain for Domain Controllers vulnerable to CVE-2020-1472.

## Installation
Requires Python 3.7 or higher and Pip. Install dependencies as follows:

    pip install -r requirements.txt

Note that running pip install impacket should work as well, as long as the script is not broken by future Impacket versions.

## Running the script

The script gets a domain as an input and ask for any domain user and his password. The user doesn't have to be an admin user.
It retrieves the list of DCs from the domain using LDAP query, and uses Secura's script to test which DC is compromised

    ./silverfort_zerologon_scanner.py EXAMPLE-DOMAIN
