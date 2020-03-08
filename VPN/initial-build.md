# OpenVPN Server Initial Build

How the OpenVPN server was originally built and configured

## Goals

- Allow for admins and developers to access the internal environment
- Utilize split-tunneling to reduce bandwith requirements
- Alloow for local authentication (temporary)
  - Will be replaced with central authentication server

## Resources used

[DigitalOcean Marketplace](https://marketplace.digitalocean.com/apps/openvpn-access-server)

## Steps taken

- Requested a new node from the DigitalOcean Marketplace, and followed configuration instructions
- Setup DNS record for vpn.drewburr.com to point to this droplet
- Logged into the server as root, and followed the setup prompts
- Setup a local user using the [admin UI](https://vpn.drewburr.com/admin)
  - Also granted admin access
- Downloaded client application through the [user UI](https://vpn.drewburr.com)
- Verified ability to connect to the VPN
- Restricted admin web server access to internal only
  - Requires VPN access to administer the VPN server
