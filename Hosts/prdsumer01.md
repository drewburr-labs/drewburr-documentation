# prdsummer01

A locally-hosted server, currently separated from the rest of the envronment.

> Getting this host connected with the rest of the enviroment will require supporting a hybrid environment. As this task would require dynamic routing, we're going to delay this task until necesary.

## Applications

### httpd (Apache)

httpd is being utilized for proxying host connections. The intention is to provide SSL certificates easily, without requiring each application to have custom configuration. This is achieved by configuring the application's service port to be 1 higher than the default (e.g. 80 -> 81), ensuring this port is blocked via `firewalld`, and configuring `httpd` to proxy this connection.

#### httpd proxies

Proxied connections are setup using virtual hosts, which are defined under `/etc/httpd/conf.d/appname.conf`

Most virtual hosts will have the following configuration:

```html
<VirtualHost *:80>
  ServerName appname.drewburr.com
</VirtualHost>
```

#### Configuring firewalld

`firewall-cmd --permanent --add-port=80/tcp`

SSL certificates are being provided by `certbot`, which should be auto-renewing the certificate.
