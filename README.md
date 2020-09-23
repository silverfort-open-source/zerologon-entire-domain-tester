# Silverfort's scanner for compromised DCs with Zerologon

## Installation
The requirements are basically the same as the ones of Secura's original script except for additionally use the ldap python library.

    pip install -r requirements.txt

## Running the script

The script gets a domain as an input and ask for user and his passowrd.
It retrieves the list of DCs from the domain using LDAP query, and uses Secura's script to test which DC is compromised

    ./silverfort_zerologon_scanner.py EXAMPLE-DOMAIN
