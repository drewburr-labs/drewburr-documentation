#!/bin/bash
# Builds pve01's unattended-install ISO from the stock PVE 8.4 ISO.
#
#   ROOT_PASSWORD_HASH='$6$...' ./build.sh ~/netboot-pve
#
# <workdir> must hold proxmox-ve_8.4-1.iso and Proxmox's SHA256SUMS.
# Output: <workdir>/out/pve01.iso. It has answer.toml (with the hash and
# SSH key filled in) and first-boot.sh embedded, and boots straight into
# the automated installer.
set -euo pipefail

WORK="${1:?usage: build.sh <workdir>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ISO=proxmox-ve_8.4-1.iso
: "${ROOT_PASSWORD_HASH:?set ROOT_PASSWORD_HASH (mkpasswd -m sha-512)}"
SSH_KEY="$(head -n1 "${SSH_PUBKEY_FILE:-$HOME/.ssh/id_ed25519.pub}")"

cd "$WORK"
grep " $ISO\$" SHA256SUMS | sha256sum -c -
mkdir -p out build
sed -e "s|__ROOT_PASSWORD_HASH__|$ROOT_PASSWORD_HASH|" -e "s|__ROOT_SSH_KEY__|$SSH_KEY|" \
  "$HERE/answer.toml" >build/answer.toml
chmod 600 build/answer.toml
cp "$HERE/first-boot.sh" build/

docker run --rm -v "$WORK:/work:Z" -w /work debian:bookworm bash -euo pipefail -c "
  apt-get -qq update && apt-get -qq install -y wget ca-certificates >/dev/null
  wget -qO /etc/apt/trusted.gpg.d/proxmox-release-bookworm.gpg \
    https://enterprise.proxmox.com/debian/proxmox-release-bookworm.gpg
  echo 'deb http://download.proxmox.com/debian/pve bookworm pve-no-subscription' \
    >/etc/apt/sources.list.d/pve.list
  apt-get -qq update && apt-get -qq install -y proxmox-auto-install-assistant >/dev/null
  proxmox-auto-install-assistant validate-answer build/answer.toml
  proxmox-auto-install-assistant prepare-iso $ISO --fetch-from iso \
    --answer-file build/answer.toml --on-first-boot build/first-boot.sh \
    --output out/pve01.iso
  chown -R $(id -u):$(id -g) out build
"
rm -rf build
ls -lh out/
