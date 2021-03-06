# Silverfort's scanner for compromised DCs with Zerologon

## Installation
Based on the Secura's code: https://github.com/SecuraBV/CVE-2020-1472/blob/master/zerologon_tester.py 
If you run the script in a Windows environment please make sure the you have the PowerShell "ActiveDirectory" module installed, 
if you don't please follow this guide: https://4sysops.com/wiki/how-to-install-the-powershell-active-directory-module/ 
In case your computer runs other operating system or you want to use LDAP/LDAPS query, please make sure you have all the 
dependencies described here: https://www.python-ldap.org/en/python-ldap-3.3.0/installing.html. 
For installing all the relevant python modules use -i.

## Running the script

The script gets a domain as an input and returns the list of Domain Controller under the domain. For Windows environments 
the script uses PowerShell commands to retrieve the list of DCs. In other environments, the script uses LDAP/LDAPS query 
and therefore it requires also the username and password of any domain user (not necessarily admin). Example of running the scipt:

    ./zerologon_tester.py EXAMPLE-DOMAIN
    
For any questions, please contact info@silverfort.com

