# NetApp NAJ-1001 JBOD

A 2U, 24-bay 2.5" SAS disk shelf used as standalone storage expansion.

## Hardware

| Component | Details |
|-----------|---------|
| Model | NetApp NAJ-1001 |
| Form Factor | 2U rackmount |
| Drive Bays | 24x 2.5" SAS/SATA |
| Drives | 24x 900GB 10K RPM SAS (2.5") |
| I/O Modules | 2x IOM6 (redundant) |
| Fans | 2x blower/impeller fan modules (hot-swap) |
| Connectivity | SAS expansion + ACP Ethernet (per IOM) |

## IOM6 Management Access

Each IOM6 module has an ACP (Alternate Control Path) Ethernet port. When not connected to a NetApp ONTAP controller, the IOM self-assigns a link-local address.

**Known IOM address:** `169.254.6.94` (MAC: `00:a0:98:89:51:56`)
**Link speed:** 100Mbps (Fast Ethernet)
**Open ports:** SSH (22) — OpenSSH 4.7

### Connecting via SSH

Modern OpenSSH clients (8.8+) and Fedora's system crypto policies block the legacy algorithms the IOM6 requires. Use a container with an older SSH client to connect:

```bash
# Start the container (one-time setup)
podman run -d --name iom6 --network=host ubuntu:18.04 sleep infinity
podman exec iom6 bash -c "apt-get update -qq && apt-get install -y -qq openssh-client"

# Connect
podman exec -it iom6 ssh -o StrictHostKeyChecking=no -o Ciphers=+aes256-cbc,3des-cbc admin@169.254.6.94
```

Your machine needs a 169.254.x.x address on the interface connected to the IOM:

```bash
sudo ip addr add 169.254.1.1/16 dev <interface>
```

**IOM6 SSH algorithm requirements:**

- Host key types: `ssh-rsa`, `ssh-dss`
- Ciphers: `3des-cbc`, `aes256-cbc`
- These are blocked by default on modern OpenSSH + Fedora crypto policy — hence the container workaround

**Credentials:** Unknown — extensive brute force attempted, no valid credentials found yet.

Tried usernames: `admin`, `root`, `naroot`, `diag`, `service`, `netapp`, `operator`, `maintenance`
Tried passwords: blank, common passwords, both chassis serial numbers (`SHFGD1551001028`, `7907726226`) and variations
Active: hydra running 10k common + SecLists default-credentials wordlists via the `iom6` podman container

**Auth methods accepted by server:** `publickey`, `password`, `keyboard-interactive`

### Chassis Info

| Label | Value |
|-------|-------|
| Chassis serial | `SHFGD1551001028` |
| Secondary serial | `7907726226` |
| Shelf ID display | Configurable via orange button on front-right panel (cycles 2-digit ID) |

## SAS Connectivity

The IOM6 host-side ports are **SFF-8088** (external mini-SAS). To connect a host with an SFF-8643 (internal mini-SAS HD) card:

**Cable needed:** SFF-8643 → SFF-8088 (search "mini-SAS HD to mini-SAS external")
**Status:** Cable ordered, arriving later this week.

Once connected, fan speed can be controlled via **SES (SCSI Enclosure Services)** using `sg_ses` from the `sg3_utils` package — no SSH credentials required.

```bash
# Install sg3_utils
sudo dnf install sg3_utils

# Discover enclosure device (after SAS connected)
sg_ses /dev/sg0

# Query fan/environmental status
sg_ses --page=2 /dev/sg0
```

## Fan Noise

The shelf is significantly loud due to its two blower fan modules. This is the primary issue being investigated.

**Fan architecture:**

- 2x hot-swap impeller/blower fan modules (replaceable as modules)
- Fan speed controlled by IOM6 firmware
- Without an ONTAP controller, fans run at full speed as a failsafe
- PWM control is not externally accessible — must go through IOM firmware or SES

**Investigation paths:**

1. **SSH CLI** — blocked pending credentials
2. **SES over SAS** — cable ordered, preferred path, bypasses credential issue entirely

## Current Status

- [x] IOM6 ACP Ethernet reachable at `169.254.6.94`
- [x] SSH port confirmed open (port 22, OpenSSH 4.7)
- [x] SSH legacy cipher workaround documented (Ubuntu 18.04 container)
- [ ] SSH login credentials confirmed
- [ ] SAS cable connected and SES tested
- [ ] Fan control achieved
- [ ] Fan noise resolution
