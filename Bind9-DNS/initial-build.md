# Bind9 DNS Server Initial Build

How the Bind9 DNS server was originally built and configured

## Goals

- Provide an internal DNS server for hosts in the environent to use

## Resources used

[DigitalOcean Guide](https://www.digitalocean.com/community/tutorials/how-to-configure-bind-as-a-private-network-dns-server-on-ubuntu-18-04)

## Steps taken

- Enabled private networking on all hosts
- Followed DigitalOcean guide for setup
  - Configure primary DNS server
    - /etc/bind/named.conf.options
    - /etc/bind/named.conf.local
    - /etc/bind/zones/db.drewburr.com
    - /etc/bind/zones/db.10.132
  - Configure clients to use DNS server
    - /etc/netplan/00-private-nameservers.yaml
