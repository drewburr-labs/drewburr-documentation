# External automation

A collection of ways to enable external automation to reach into the environment (e.g. Deploying from github.com).

## Preface

Right now, the only way to reach into the environemtn is by first connecting to the VPN. This will require a service account to be setup in FreeIPA. No special permissions are needed to connect to the VPN. This guide assumes the service account is already setup.

> Deploying without a dedicated service account is possible, but is bad practive. Do not do this.

## Connecting the the VPN

Here we'll outline the ways in which a VPN connection can be setup.

- [OpenConnect and CLI](#OpenConnect-and-CLI)
- [OpenConnect with GitHub Actions](#OpenConnect-with-GitHub-Actions)

### OpenConnect via CLI

The most straightforward method of connecting to the VPN is through CLI.

#### OpenConnect

##### Install OpenConnect

OpenConnect must be installed for this to work. Most distros ship with OpenConnect available, however the below command will differ depending on the package installer.

`sudo apt install openconnect`

##### Connect to OpenConnect

The command to connect to OpenConnect _must_ be executed as root. The below command provideds a way to pass in the service accounts password through a environment variable, which is enabled with the `--passwd-on-stdin` flag. The `--background` flag is also required, otherwise your the command will not exit without user intervention. At this point, you are connected to the environment.

`echo "$SSH_PASS" | sudo openconnect vpn2.drewburr.com --user=$SERVICE_ACCT --passwd-on-stdin --background --http-auth=BASIC`

##### Kill OpenConnect Connection

After deploying, it is best practice to kill the VPN connection. This can be done with the below command, which must be executed as root.

`sudo killall openconnect`

### OpenConnect with GitHub Actions

Similar to the CLI-based deployment, here we'll be connecting to the VPN with OpenConnect during actions that require the environment being available. Ideally, we want to connect to the VPN only when required. This will help reduce reource usage and improve experience of others when using the VPN.

> If downloads to the action container are reqired after connecting the the VPN, consider disconnecting from the VPN for those steps. This would be done by killing the VPN, then running the connection action again.

#### Example Actions

```yaml
- name: Install OpenConnect
  run: sudo apt install openconnect

- name: Other setup actions
  run: ...

- name: Connect to OpenConnect
  run: echo '${{ secrets.SSH_PASS }}' | sudo openconnect vpn2.drewburr.com --user=${{ secrets.SSH_USER }} --passwd-on-stdin --background --http-auth=BASIC

- name: Deploy to environment
  run: ...

- name: Kill the VPN
  if: always()
  run: sudo killall openconnect

- name: Post-deployment steps
  run: ...
```
