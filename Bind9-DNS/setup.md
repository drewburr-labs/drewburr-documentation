# Bind9 DNS Server Setup

Documentation relateed to the setup and configuration of the Bind9 DNS server.

## Goals

- Provide an internal DNS server for hosts in the environent to use

## Helpful resources

[DigitalOcean Guide](https://www.digitalocean.com/community/tutorials/how-to-configure-bind-as-a-private-network-dns-server-on-ubuntu-18-04)

## Key configuration

### Server configuration

#### named.conf.options

> /etc/bind/named.conf.options

- Sets bind directory to `/var/cache/bind`
- Setup of ACL for trusted IP addresses
  - Allows for recursive queries
  - Internal subnet needs to be present `10.132.0.0/16`
  - VPN client subnet needs to be present `172.27.224.0/20`
- Sets the listen IP address t othe internal interface `10.132.29.121`
- Disables zone transfers
- Sets DNS forwarders to `8.8.8.8` and `8.8.4.4`

#### named.conf.local

> /etc/bind/named.conf.local

- Setup of DNS zones
  - drewburr.com
    - `/etc/bind/zones/db.drewburr.com`
  - 132.10.in-addr.arpa
    - `/etc/bind/zones/db.10.132`

#### db.drewburr.com

> /etc/bind/zones/db.drewburr.com

NS records and A records

#### db.10.132

> /etc/bind/zones/db.10.132

PTR records for `10.132.0.0/16` subnet

### Client configuration

> /etc/netplan/00-private-nameservers.yaml

Configures DNS settings on the internal interface

- Sets nameserver IP addresses `10.132.29.121`
  - On the DSN server, `127.0.0.1` is also included
- Sets the default DNS search zone to `drewburr.com`
