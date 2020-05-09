# Tips and tricks

A list of helpful commands and topics, mostly for reference

## Index

- [Managing SSL certificates with certbot](#Managing-SSL-certificates-with-certbot)
- [Adding a host to FreeIPA](#Adding-a-host-to-FreeIPA)
- [Adding SSH public key to FreeIPA](#Adding-SSH-public-key-to-FreeIPA)

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

## Adding a host to FreeIPA

This guide is meant to outline the process for adding a new server to FreeIPA.

Install `ipa-client-install`

- Ubuntu
  - `apt install freeipa-client`
- CentOS
  - `yum install ipa-client`

When prompted, use the below settings.

> Domain: DREWBURR.COM
> Kerberos server: prdipa01.drewburr.com
> Directory Server: prdipa01.drewburr.com

After installation is complete, run the below command to install the FreeIPA client.

```shell
ipa-client-install --enable-dns-updates --mkhomedir --domain=DREWBURR.COM --server=prdipa01.drewburr.com
```

If you receive the error `hostname is not a fully-qualified hostname`, update your host's hostname to be fully-qualified with `hostnamectl`.

```shell
root@prdzone1 ~ # hostnamectl
   Static hostname: prdzone1
    ...
root@prdzone1 ~ # hostnamectl set-hostname prdzone1.drewburr.com
root@prdzone1 ~ # hostnamectl
   Static hostname: prdzone1.drewburr.com
    ...
```

When installing, you'll receive several prompts. Below is the expected prompts and responses. When prompted for an authorized user, any FreeIPA administrative account will work.

```shell
root@prdzone1 ~ # ipa-client-install --enable-dns-updates --mkhomedir --domain=DREWBURR.COM --server=prdipa01.drewburr.com
WARNING: conflicting time&date synchronization service 'ntp' will be disabled
in favor of chronyd

Autodiscovery of servers for failover cannot work with this configuration.
If you proceed with the installation, services will be configured to always access the discovered server for all operations and will not fail over to other servers in case of failure.
Proceed with fixed values and no DNS discovery? [no]: yes
Client hostname: prdzone1.drewburr.com
Realm: DREWBURR.COM
DNS Domain: drewburr.com
IPA Server: prdipa01.drewburr.com
BaseDN: dc=drewburr,dc=com

Continue to configure the system with these values? [no]: yes
```

Installation should now be completed. This can be tested using `id` and `nslookup`.

## Adding SSH public key to FreeIPA

Run the following command on a FreeIPA-joined host to load your pubic key into FreeIPA.

`ipa user-mod <user> --sshpubkey "$( cat /path/to/id_rsa.pub )"`
