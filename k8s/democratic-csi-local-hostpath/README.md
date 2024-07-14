# democratic-csi

[democratic-csi/democratic-csi](https://github.com/democratic-csi/democratic-csi)

The following waqs used to prepare a disk each node:

```sh
sudo fdisk /dev/sdb
# Command (m for help): n
# Partition type
#    p   primary (0 primary, 0 extended, 4 free)
#    e   extended (container for logical partitions)
# Select (default p): p
# Partition number (1-4, default 1): 1
# First sector (2048-976764927, default 2048): 2048
# Last sector, +/-sectors or +/-size{K,M,G,T,P} (2048-976764927, default 976764927): 976764927

# Created a new partition 1 of type 'Linux' and of size 465.8 GiB.

# Command (m for help): w
# The partition table has been altered.
# Calling ioctl() to re-read partition table.
# Syncing disks.
mkfs.ext4 /dev/sdb1
sudo blkid /dev/sdb1
# /dev/sdb1: UUID="1cfb14d4-4896-4477-b0ca-bba532c344b7" BLOCK_SIZE="4096" TYPE="ext4" PARTUUID="3d283586-01"
echo "$(sudo blkid /dev/sdb1 | cut -d' ' -f2) /mnt/csi-local ext4  defaults   0 0" >> /etc/fstab
mkdir -p /mnt/csi-local
mount -a
df -h
# /dev/sdb1       458G   28K  435G   1% /mnt/csi-local
```

Next, dependencies were installed:

```sh
sudo apt-get install -y cifs-utils nfs-common
```
