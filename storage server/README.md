# Storage Server Documentation

Now that I have 10GbE + 2.5GbE network capabilities, I've built a storage server and intend to use it for centralized storage for Kubernetes PVCs. This server will run as a VM in Proxmox, with PCI passthrough of a SAS card. THe hope is that a backup of the VM is a backup of the ZFS configuration, then I can handle PVC backups at the Kuberentes level.

Storage will be provided using ZFS, nvmeof, and the democratic-csi operator. I originally considered iSCSI but found several resources referencing performance improvements of nvmeof, so we're going with that.

## ZFS setup

Following the somedudesays [ZFS overview](https://somedudesays.com/2021/08/the-basic-guide-to-working-with-zfs/)

```sh
# Install ZFS
sudo apt install zfsutils-linux

sudo zpool create sas-pool raidz3 /dev/sdd /dev/sdb /dev/sde /dev/sdi /dev/sdc /dev/sdf /dev/sdm /dev/sdj /dev/sdh /dev/sdk /dev/sdg /dev/sdl
```

## nvmeof setup

### Client

```sh
# not required but likely helpful (tools are included in the democratic images
# so not needed on the host)
apt install -y nvme-cli

# get the nvme fabric modules
apt install linux-generic

# ensure the nvmeof modules get loaded at boot
cat <<EOF > /etc/modules-load.d/nvme.conf
nvme
nvme-tcp
nvme-fc
nvme-rdma
EOF

# load the modules immediately
modprobe nvme
modprobe nvme-tcp
modprobe nvme-fc
modprobe nvme-rdma

## DID NOT DO THE BELOW ##

# nvme has native multipath or can use DM multipath
# democratic-csi will gracefully handle either configuration
# RedHat recommends DM multipath (nvme_core.multipath=N)
cat /sys/module/nvme_core/parameters/multipath

# kernel arg to enable/disable native multipath
nvme_core.multipath=N
```

### Server

Followed democratic-csi [installation steps](https://github.com/democratic-csi/democratic-csi?tab=readme-ov-file#zol-zfs-generic-nfs-zfs-generic-iscsi-zfs-generic-smb-zfs-generic-nvmeof)

```sh
sudo -i
apt install nvme-cli -y

# get the nvme fabric modules
apt install linux-generic -y

# ensure nvmeof target modules are loaded at startup
cat <<EOF > /etc/modules-load.d/nvmet.conf
nvmet
nvmet-tcp
nvmet-fc
nvmet-rdma
EOF

# load the modules immediately
modprobe nvmet
modprobe nvmet-tcp
modprobe nvmet-fc
modprobe nvmet-rdma

# install nvmetcli and systemd services
git clone git://git.infradead.org/users/hch/nvmetcli.git
cd nvmetcli

## install globally
python3 setup.py install --prefix=/usr
apt install python3-pip -y
pip install configshell_fb

## install to root home dir
python3 setup.py install --user
pip install configshell_fb --user

# prevent log files from filling up disk
mkdir ~/.nvmetcli
ln -sf /dev/null ~/.nvmetcli/log.txt
ln -sf /dev/null ~/.nvmetcli/history.txt

# install systemd unit and enable/start
## optionally to ensure the config file is loaded before we start
## reading/writing to it add an ExecStartPost= to the unit file
##
## ExecStartPost=/usr/bin/touch /var/run/nvmet-config-loaded
##
## in your dirver config set nvmeof.shareStrategyNvmetCli.configIsImportedFilePath=/var/run/nvmet-config-loaded
## which will prevent the driver from making any changes until the configured
## file is present
vi nvmet.service

# install, start, and enable service
cp nvmet.service /etc/systemd/system/
mkdir -p /etc/nvmet
systemctl daemon-reload
systemctl enable --now nvmet.service
systemctl status nvmet.service

# create the port(s) configuration manually
echo "
cd /
ls
" | nvmetcli

# do this multiple times altering as appropriate if you have/want multipath
# change the port to 2, 3.. each additional path
# the below example creates a tcp port listening on all IPs on port 4420
echo "
cd /ports
create 1
cd 1
set addr adrfam=ipv4 trtype=tcp traddr=0.0.0.0 trsvcid=4420

saveconfig /etc/nvmet/config.json
" | nvmetcli
```

## SSH key generation

The client/server pair will use an SSH key for authentication. We will create a dedicated key for this purpose:

```sh
ssh server_hostname

# Generate key pair and add to authorized keys
ssh-keygen -f /home/ubuntu/.ssh/id_rsa_zfs_nvmeof -N ''
cat ~/.ssh/id_rsa_zfs_nvmeof.pub >> ~/.ssh/authorized_keys

# Get the public key and create a secret containing its value
```
