# Ceph

```shell
kubens ceph-csi-rbd
helm template ceph . > template.yaml
```

## ceph-testing container

```shell
# Troughput
dd if=/dev/zero of=/tmp/test1.img bs=1G count=1 oflag=dsync
dd if=/dev/zero of=./test bs=512k count=2048 oflag=direct

# Latency
dd if=/dev/zero of=/tmp/test2.img bs=512 count=1000 oflag=dsync

# # Buffered and cached disk speed
# Write
hdparm -t /dev/sda
# Read
hdparm -T /dev/sda
# Both
hdparm -Tt /dev/sda

# Drop caches before reads - doesn't work in pod
echo 3 | sudo tee /proc/sys/vm/drop_caches

# Read speed test
dd if=/path/to/bigfile of=/dev/null bs=8k
```
