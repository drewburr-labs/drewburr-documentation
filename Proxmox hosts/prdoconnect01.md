# prdoconnect01.drewburr.com

OpenConnect server

```text
OpenConnect server (ocserv) is an SSL VPN server. Its purpose is to be a
secure, small, fast and configurable VPN server. It implements the OpenConnect
SSL VPN protocol, and has also (currently experimental) compatibility with
clients using the AnyConnect SSL VPN protocol. The OpenConnect VPN protocol
uses the standard IETF security protocols such as TLS 1.2, and Datagram TLS
to provide the secure VPN service.
```

## Server specs

CentOS 8.2

- 1 socket, 2 core
- 3072MB RAM
- 32GB Disk
- 192.168.1.106

## Setup

### Resources used

- [ocserv installation cook-book](http://www.infradead.org/ocserv/recipes-ocserv-installation-CentOS-RHEL-Fedora.html)
- [Authentiction with FreeIPA](https://github.com/openconnect/recipes/blob/master/ocserv-freeipa.md)
- [ocserv official documentation](https://ocserv.gitlab.io/www/recipes-ocserv-installation-CentOS-RHEL-Fedora.html)
- [ocserv service configuration](https://github.com/openconnect/ocserv/blob/master/doc/systemd/standalone/ocserv.service)
- [official instructions w/ letsencrypt](https://ocserv.gitlab.io/www/recipes-ocserv-certificates-letsencrypt.html)

## Setup and inststallation walkthrough

Host was setup using the DNS name `vpn.drewburr.com`.

First installed ocserv using the [ocserv installation cook-book](http://www.infradead.org/ocserv/recipes-ocserv-installation-CentOS-RHEL-Fedora.html).

The application was configured using the [official instructions w/ letsencrypt](https://ocserv.gitlab.io/www/recipes-ocserv-certificates-letsencrypt.html).

> NOTE: GSSAPI authentication was not setup due to some errors that could not be resolved. Authentication works regardless, so the impact of doing so is not known.

```shell
## ocserv installation cook-book ##
yum update
yum install epel-release
yum install ocserv
## Authentiction with FreeIPA ##
yum install certbot
firewall-cmd --add-port 80/tcp
firewall-cmd --add-port 80/udp
firewall-cmd --reload
certbot certonly --standalone --preferred-challenges http --agree-tos --email drewburr9@gmail.com -d vpn.drewburr.com
# Add the following to /etc/crontab
# 15 00 * * * root certbot renew --quiet && systemctl restart ocserv
vi /etc/ocserv/ocserv.conf
# default-domain = drewburr.com
# ipv4-network = 192.168.5.0
# ipv4-netmask = 255.255.255.0
# tunnel-all-dns = true
# dns = 192.168.1.101
# server-cert = /etc/letsencrypt/live/vpn.drewburr.com/fullchain.pem
# server-key = /etc/letsencrypt/live/vpn.drewburr.com/privkey.pem
firewall-cmd --add-port 443/tcp
firewall-cmd --add-port 443/udp
firewall-cmd --reload
systemctl enable ocserv.service
systemctl start ocserv.service
```
