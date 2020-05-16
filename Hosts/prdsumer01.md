# prdsummer01

A locally-hosted server, currently separated from the rest of the envronment.

> Getting this host connected with the rest of the enviroment will require supporting a hybrid environment. As this task would require dynamic routing, we're going to delay this task until necesary.

## Applications

### Terraria server

#### Baseline info

The `relogic` service account is the owner of all Terraria data. This users home directory is under `/srv/terraria`. Relgic is a member of the `docker` group, and therefore is allowed to execute Docker commands. The Terraria will be run from a Docker container, and hosted on port **7777** (default). This post has been opened for both UDP and TCP.

## Configuring firewalld

`firewall-cmd --permanent --add-port=80/tcp`

SSL certificates are being provided by `certbot`, which should be auto-renewing the certificate.
