# prdoconnect01

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

CentOS 8

- 2 vCPU
- 2GB RAM
- 60GB Disk

## Setup

### Resources used

[ocserv official documentation](https://ocserv.gitlab.io/www/recipes-ocserv-installation-CentOS-RHEL-Fedora.html)
[ocserv service configuration](https://github.com/openconnect/ocserv/blob/master/doc/systemd/standalone/ocserv.service)
[Certificate setup](https://ocserv.gitlab.io/www/recipes-ocserv-certificates-letsencrypt.html)

To install `certbot`, run the following:

```shell
dnf config-manager --set-enabled PowerTools
dnf install certbot
```

### Split-tunnel setup

[Setting kernel capabilities](https://gist.github.com/stefancocora/686bbce938f27ef72649a181e7bd0158#openconnect-binary-kernel-capabilities)

## Setup and inststallation walkthrough

Host was initially setup using the DNS name `vpn2.drewburr.com`. This was to allow for the buildout of a 2nd VPN and transition over from `vpn.drewburr.com` as-needed.

The host is built out following the [official instructions w/ letsencrypt](https://ocserv.gitlab.io/www/recipes-ocserv-certificates-letsencrypt.html), with some differences regarding how the certs are referenced.

Certificates are referenced by setting the following in `/etc/ocserv/ocserv.conf`.

```text
server-cert = /etc/letsencrypt/live/vpn2.drewburr.com/fullchain.pem
server-key = /etc/letsencrypt/live/vpn2.drewburr.com/privkey.pem
```
