# drewburr documentation

Documentation related the the drewburr environment

## Hosts

### prdzone1

Admin server. Holds the global root SSH keys.

Externally open ports

- None

### openvpn

VPN and DNS servers live here.

Externally open ports

- VPN
  - 443 (TCP)
  - 1194 (UDP)

### prdsummer01

Self-hosted server. Intended for resource-intensive computing, personal testing, and to save money.

## Applications

### VPN Server

- [Initial Build](OpenVPN/initial-build.md)
- [Current Setup](OpenVPN/setup.md)

### DNS Server

- [Initial Build](Bind9-DNS/initial-build.md)
- [Current Setup](Bind9-DNS/setup.md)
