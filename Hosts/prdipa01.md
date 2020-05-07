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

## Signed certificate setup

Certs are curently self-sined. There was an effort to get signed certificates from

[Setup of client cert](https://blog.soholabs.org/lets-encrypt-and-the-freeipa-web-gui/)
[lets-encrypt-x3-cross-signed](https://letsencrypt.org/certs/lets-encrypt-x3-cross-signed.pem.txt)

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

## Adding a host to FreeIPA

```shell
kinit <user>
ipa service-add HTTP/<host_fqdn>
```

### On the target host

Ensure hostname is fully-qualified before starting this process. If the hostname is not fully-qualified, execute `hostnamectl set-hostname hostname.domain.com` to update it.

```shell
yum install ipa-client
ipa-client-install --enable-dns-updates
```

```shell
[root@prdoconnect01 ~]# ipa-client-install --enable-dns-updates --force-ntpd --password='password' --principal=admin_user --realm=DREWBURR.COM --ssh-trust-dns
Option --force-ntpd has been deprecated and will be removed in a future release.
This program will set up IPA client.
Version 4.8.0

DNS discovery failed to determine your DNS domain
Provide the domain name of your IPA server (ex: example.com): drewburr.com
Provide your IPA server name (ex: ipa.example.com): prdipa01.drewburr.com
The failure to use DNS to find your IPA server indicates that your resolv.conf file is not properly configured.
Autodiscovery of servers for failover cannot work with this configuration.
If you proceed with the installation, services will be configured to always access the discovered server for all operations and will not fail over to other servers in case of failure.
Proceed with fixed values and no DNS discovery? [no]: yes
Do you want to configure chrony with NTP server or pool address? [no]:
Client hostname: prdoconnect01.drewburr.com
Realm: DREWBURR.COM
DNS Domain: drewburr.com
IPA Server: prdipa01.drewburr.com
BaseDN: dc=drewburr,dc=com

Continue to configure the system with these values? [no]: yes
Synchronizing time
No SRV records of NTP servers found and no NTP server or pool address was provided.
Using default chrony configuration.
Attempting to sync time with chronyc.
Time synchronization was successful.
Successfully retrieved CA cert
    Subject:     CN=Certificate Authority,O=DREWBURR.COM
    Issuer:      CN=Certificate Authority,O=DREWBURR.COM
    Valid From:  2020-04-28 03:18:42
    Valid Until: 2040-04-28 03:18:42

Enrolled in IPA realm DREWBURR.COM
Created /etc/ipa/default.conf
Configured sudoers in /etc/authselect/user-nsswitch.conf
Configured /etc/sssd/sssd.conf
Configured /etc/krb5.conf for IPA realm DREWBURR.COM
Systemwide CA database updated.
Failed to update DNS records.
Adding SSH public key from /etc/ssh/ssh_host_ecdsa_key.pub
Adding SSH public key from /etc/ssh/ssh_host_ed25519_key.pub
Adding SSH public key from /etc/ssh/ssh_host_rsa_key.pub
Could not update DNS SSHFP records.
SSSD enabled
Configured /etc/openldap/ldap.conf
Configured /etc/ssh/ssh_config
Configured /etc/ssh/sshd_config
Configuring drewburr.com as NIS domain.
Client configuration complete.
The ipa-client-install command was successful

```
