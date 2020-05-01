# OpenVPN Server Setup

Documentation relateed to the setup and configuration of the OpenVPN server.

## Goals

- Allow for admins and developers to access the internal environment
- Utilize split-tunneling to reduce bandwith requirements
- Alloow for local authentication (temporary)
  - Will be repalced with central authentication server

## Helpful resources

[DigitalOcean Marketplace](https://marketplace.digitalocean.com/apps/openvpn-access-server)

## Key configuration

### Routing

- Enable routing using NAT
- Do not route all client traffic through the VPN
  - Trying to preserve bandwith
- Clients should be able to access services on the VPN gateway
  - I believe this means that the VPN host itself should be accessible when using the VPN

### DNS Settings

- Have clients use the same DNS settings as the Access Server
- Do not use a DNS resolution zone
  - Creates DNS issues on Windows devices (nslookup does not work)
- Do not set a default domain suffix
  - Cripples Spotify :(

## Tips and tricks

Clear DNS cache on Ubuntu

`systemd-resolve --flush-caches`
