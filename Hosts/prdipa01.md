# prdipa01

FreeIPA host, used for DNS and LDAP authentication

## Specs

CentOS 8

- 1 vCPU
- 3GB RAM
- 60GB Disk

## Resources Used

[Official Quick Start Guide](https://www.freeipa.org/page/Quick_Start_Guide)
[Installation Guide by computingforgeeks (Centos 8 specific)](https://computingforgeeks.com/how-to-install-and-configure-freeipa-server-on-rhel-centos-8/)

For the install command, we ran th following to enable DNS, and ignore existing DNS entries

`ipa-server-install --setup-dns --allow-zone-overlap`

## Required Ports

```text
TCP Ports:
  * 80, 443: HTTP/HTTPS
  * 389, 636: LDAP/LDAPS
  * 88, 464: kerberos
  * 53: bind
UDP Ports:
  * 88, 464: kerberos
  * 53: bind
  * 123: ntp
```
