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

- [ocserv official documentation](https://ocserv.gitlab.io/www/recipes-ocserv-installation-CentOS-RHEL-Fedora.html)
- [ocserv service configuration](https://github.com/openconnect/ocserv/blob/master/doc/systemd/standalone/ocserv.service)
- [Certificate setup](https://ocserv.gitlab.io/www/recipes-ocserv-certificates-letsencrypt.html)
- [Authentiction with FreeIPA](https://github.com/openconnect/recipes/blob/master/ocserv-freeipa.md)

## Setup and inststallation walkthrough

Host was initially setup using the DNS name `vpn2.drewburr.com`. This was to allow for the buildout of a 2nd VPN and transition over from `vpn.drewburr.com` as-needed.

The host is built out following the [official instructions w/ letsencrypt](https://ocserv.gitlab.io/www/recipes-ocserv-certificates-letsencrypt.html), with some differences regarding how the certs are referenced.

Certificates were setup through instructions referenced in `Authentiction with FreeIPA` (linked above).

> NOTE: GSSAPI authentication was not setup due to some errors that could not be resolved. Authentication works regardless, so the impact of doing so is not known.
