# Tips and tricks

A list of helpful commands and topics, mostly for reference

## Managing SSL certificates with certbot

Installation instructions [here](https://certbot.eff.org/lets-encrypt/centosrhel8-other)

```shell
# Generate a certificate
certbot-auto certonly --standalone --preferred-challenges http --agree-tos --email drewburr9@gmail.com -d hostname.drewburr.com
```

> NOTE: It's worth considering having crontab restart your app's services with a cert renewal

Cerfiticates can be linked directly through a config files, or thorugh symlinks.

```text
server-cert = /etc/letsencrypt/live/hostname.drewburr.com/fullchain.pem
server-key = /etc/letsencrypt/live/hostname.drewburr.com/privkey.pem
```

```shell
ln -s /path/to/cert /path/to/link
```
