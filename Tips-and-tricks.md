# Tips and tricks

A list of helpful commands and topics, mostly for reference

## Managing SSL certificates with certbot

```shell
# Installling certbot (CentOS 8)
dnf config-manager --set-enabled PowerTools
dnf install certbot

# Generate a certificate
certbot certonly --standalone --preferred-challenges http --agree-tos --email drewburr9@gmail.com -d hostname.drewburr.com

# Auto-renew certificates w/ crontab
crontab -e
# Add the following to crontab
15 00 * * * root certbot renew --quiet
```

> NOTE: It's worth considering having crontab restart your app's services with a cert renewal

Cerfiticates can be linked directly through a config files, or thorugh symlinks.

```text
server-cert = /etc/letsencrypt/live/vpn2.drewburr.com/fullchain.pem
server-key = /etc/letsencrypt/live/vpn2.drewburr.com/privkey.pem
```

```shell
ln -s /path/to/cert /path/to/link
```
