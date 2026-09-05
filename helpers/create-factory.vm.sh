#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# Soft Factory - VM bootstrap
#
# Host:
#   Oracle Linux Server 9.7
#   KVM / libvirt
#
# Guest:
#   Ubuntu Server 24.04 LTS
#
# Network:
#   libvirt Direct / macvtap
#   source interface: enp129s0f1
#   source mode: bridge
#   static guest IP: 10.9.20.101
#
# Usage:
#   chmod +x create-factory-vm.sh
#   sudo ./create-factory-vm.sh
#
# Optional overrides:
#   sudo env \
#     GATEWAY_OVERRIDE=10.9.20.1 \
#     PREFIX_OVERRIDE=24 \
#     DNS1_OVERRIDE=10.9.20.1 \
#     ./create-factory-vm.sh
# ============================================================================

# ----------------------------------------------------------------------------
# VM CONFIGURATION
# ----------------------------------------------------------------------------

VM_NAME="${VM_NAME:-soft-factory}"
VM_USER="${VM_USER:-factory}"

VCPUS="${VCPUS:-8}"
RAM_MB="${RAM_MB:-32768}"
DISK_SIZE="${DISK_SIZE:-120G}"

IMAGE_DIR="${IMAGE_DIR:-/var/lib/libvirt/images}"

HOST_IF="${HOST_IF:-enp129s0f1}"

VM_IP="${VM_IP:-10.9.20.101}"
VM_MAC="${VM_MAC:-52:54:00:09:21:64}"
GATEWAY_OVERRIDE="${GATEWAY_OVERRIDE:-10.9.20.1}"

UBUNTU_RELEASE="${UBUNTU_RELEASE:-24.04}"
UBUNTU_BASE_URL="https://cloud-images.ubuntu.com/releases/${UBUNTU_RELEASE}/release"
UBUNTU_IMAGE="ubuntu-${UBUNTU_RELEASE}-server-cloudimg-amd64.img"

BASE_IMAGE="${IMAGE_DIR}/ubuntu-${UBUNTU_RELEASE}-server-cloudimg-amd64.img"
VM_DISK="${IMAGE_DIR}/${VM_NAME}.qcow2"
SEED_ISO="${IMAGE_DIR}/${VM_NAME}-seed.iso"

# ----------------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------------

log() {
    printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

die() {
    printf '\nERROR: %s\n' "$*" >&2
    exit 1
}

unit_exists() {
    systemctl list-unit-files "$1" >/dev/null 2>&1
}

# ----------------------------------------------------------------------------
# ROOT CHECK
# ----------------------------------------------------------------------------

if [[ "$(id -u)" -ne 0 ]]; then
    die "Uruchom skrypt jako root, np. sudo $0"
fi

REAL_USER="${SUDO_USER:-root}"
REAL_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"

if [[ -z "$REAL_HOME" ]]; then
    die "Nie udało się ustalić katalogu domowego użytkownika $REAL_USER"
fi

SSH_PUBKEY="${SSH_PUBKEY:-${REAL_HOME}/.ssh/id_ed25519.pub}"

# ----------------------------------------------------------------------------
# SUMMARY
# ----------------------------------------------------------------------------

cat <<EOF

==============================================================================
 Public Radar Factory
==============================================================================

 VM name       : ${VM_NAME}
 Guest OS      : Ubuntu Server ${UBUNTU_RELEASE} LTS
 vCPU          : ${VCPUS}
 RAM           : ${RAM_MB} MB
 Disk          : ${DISK_SIZE}

 Network type  : direct / macvtap
 Host IF       : ${HOST_IF}
 Source mode   : bridge
 Guest IP      : ${VM_IP}
 Guest MAC     : ${VM_MAC}

 Guest user    : ${VM_USER}

==============================================================================
EOF

# ----------------------------------------------------------------------------
# INSTALL HOST PACKAGES
# ----------------------------------------------------------------------------

log "Instalacja pakietów KVM/libvirt na hoście..."

dnf install -y \
    qemu-kvm \
    libvirt \
    libvirt-client \
    virt-install \
    libosinfo \
    osinfo-db \
    xorriso \
    curl \
    iproute

# ----------------------------------------------------------------------------
# START LIBVIRT DAEMONS / SOCKETS
# ----------------------------------------------------------------------------

log "Uruchamianie usług libvirt..."

LIBVIRT_UNITS=(
    virtqemud.socket
    virtlogd.socket
    virtlockd.socket
    virtproxyd.socket
    virtnetworkd.socket
    virtstoraged.socket
    virtnodedevd.socket
    virtnwfilterd.socket
    virtsecretd.socket
    virtinterfaced.socket
)

for unit in "${LIBVIRT_UNITS[@]}"; do
    if unit_exists "$unit"; then
        systemctl enable --now "$unit" || true
    fi
done

if unit_exists "libvirtd.service"; then
    systemctl enable --now libvirtd.service || true
fi

# ----------------------------------------------------------------------------
# CHECK KVM
# ----------------------------------------------------------------------------

log "Sprawdzanie KVM..."

[[ -e /dev/kvm ]] || die "Brak /dev/kvm. Sprawdź VT-x/AMD-V oraz moduły KVM."

if ! lsmod | grep -Eq '^kvm(_intel|_amd)?'; then
    modprobe kvm || true
fi

if grep -qE 'vmx|svm' /proc/cpuinfo; then
    echo "KVM hardware virtualization: OK"
else
    echo "UWAGA: nie wykryto flag vmx/svm w /proc/cpuinfo."
fi

# ----------------------------------------------------------------------------
# CHECK HOST INTERFACE
# ----------------------------------------------------------------------------

log "Sprawdzanie interfejsu ${HOST_IF}..."

ip link show "$HOST_IF" >/dev/null 2>&1 \
    || die "Interfejs ${HOST_IF} nie istnieje."

if [[ "$(cat "/sys/class/net/${HOST_IF}/operstate" 2>/dev/null || true)" != "up" ]]; then
    echo "UWAGA: ${HOST_IF} nie zgłasza stanu UP."
fi

# ----------------------------------------------------------------------------
# DETECT NETWORK PREFIX
# ----------------------------------------------------------------------------

HOST_CIDR="$(
    ip -4 -o addr show dev "$HOST_IF" scope global 2>/dev/null \
    | awk '{print $4}' \
    | head -1
)"

if [[ -n "${PREFIX_OVERRIDE:-}" ]]; then
    PREFIX="$PREFIX_OVERRIDE"
elif [[ -n "$HOST_CIDR" ]]; then
    PREFIX="${HOST_CIDR#*/}"
else
    die "Nie udało się ustalić maski/prefixu dla ${HOST_IF}. Użyj PREFIX_OVERRIDE, np. PREFIX_OVERRIDE=24"
fi

# ----------------------------------------------------------------------------
# DETECT GATEWAY
# ----------------------------------------------------------------------------

if [[ -n "${GATEWAY_OVERRIDE:-}" ]]; then
    GATEWAY="$GATEWAY_OVERRIDE"
else
    GATEWAY="$(
        ip -4 route show default dev "$HOST_IF" 2>/dev/null \
        | awk '{print $3}' \
        | head -1
    )"

    if [[ -z "$GATEWAY" ]]; then
        # fallback: default route regardless of interface
        GATEWAY="$(
            ip -4 route show default 2>/dev/null \
            | awk '{print $3}' \
            | head -1
        )"
    fi
fi

[[ -n "$GATEWAY" ]] \
    || die "Nie udało się ustalić bramy. Użyj GATEWAY_OVERRIDE, np. GATEWAY_OVERRIDE=10.9.20.1"

# ----------------------------------------------------------------------------
# DETECT DNS
# ----------------------------------------------------------------------------

if [[ -n "${DNS1_OVERRIDE:-}" ]]; then
    DNS1="$DNS1_OVERRIDE"
else
    DNS1="$(
        awk '
            /^nameserver / && $2 !~ /^127\./ && $2 != "::1" {
                print $2
                exit
            }
        ' /etc/resolv.conf 2>/dev/null || true
    )"
fi

DNS1="${DNS1:-1.1.1.1}"
DNS2="${DNS2_OVERRIDE:-8.8.8.8}"

cat <<EOF

Network configuration detected:

 Host interface : ${HOST_IF}
 Guest address  : ${VM_IP}/${PREFIX}
 Gateway        : ${GATEWAY}
 DNS 1          : ${DNS1}
 DNS 2          : ${DNS2}
 MAC            : ${VM_MAC}

EOF

# ----------------------------------------------------------------------------
# SANITY CHECK: VM IP SHOULD NOT ALREADY ANSWER
# ----------------------------------------------------------------------------

log "Sprawdzanie, czy adres ${VM_IP} nie odpowiada już w sieci..."

if ping -c 1 -W 1 "$VM_IP" >/dev/null 2>&1; then
    die "Adres ${VM_IP} już odpowiada w sieci. Nie tworzę VM."
fi

# ----------------------------------------------------------------------------
# CHECK EXISTING DOMAIN / FILES
# ----------------------------------------------------------------------------

if virsh dominfo "$VM_NAME" >/dev/null 2>&1; then
    die "Domena libvirt '${VM_NAME}' już istnieje."
fi

if [[ -e "$VM_DISK" ]]; then
    die "Plik dysku ${VM_DISK} już istnieje."
fi

if [[ -e "$SEED_ISO" ]]; then
    die "Plik ${SEED_ISO} już istnieje."
fi

mkdir -p "$IMAGE_DIR"

# ----------------------------------------------------------------------------
# SSH KEY
# ----------------------------------------------------------------------------

log "Sprawdzanie klucza SSH..."

if [[ ! -f "$SSH_PUBKEY" ]]; then
    echo "Nie znaleziono: $SSH_PUBKEY"
    echo "Tworzę nowy klucz Ed25519 dla użytkownika ${REAL_USER}..."

    if [[ "$REAL_USER" == "root" ]]; then
        install -d -m 0700 /root/.ssh
        ssh-keygen -t ed25519 -N "" -f /root/.ssh/id_ed25519
        SSH_PUBKEY="/root/.ssh/id_ed25519.pub"
    else
        install -d -m 0700 -o "$REAL_USER" -g "$REAL_USER" "${REAL_HOME}/.ssh"
        sudo -u "$REAL_USER" \
            ssh-keygen -t ed25519 -N "" -f "${REAL_HOME}/.ssh/id_ed25519"
        SSH_PUBKEY="${REAL_HOME}/.ssh/id_ed25519.pub"
    fi
fi

PUBKEY="$(cat "$SSH_PUBKEY")"

[[ -n "$PUBKEY" ]] || die "Klucz publiczny SSH jest pusty."

echo "SSH public key: ${SSH_PUBKEY}"

# ----------------------------------------------------------------------------
# DOWNLOAD UBUNTU CLOUD IMAGE
# ----------------------------------------------------------------------------

log "Pobieranie Ubuntu ${UBUNTU_RELEASE} cloud image..."

TMP_IMAGE="${BASE_IMAGE}.download"
TMP_SHA="$(mktemp)"

cleanup_tmp() {
    rm -f "$TMP_SHA" "$TMP_IMAGE" 2>/dev/null || true
}
trap cleanup_tmp EXIT

curl \
    --fail \
    --location \
    --progress-bar \
    "${UBUNTU_BASE_URL}/${UBUNTU_IMAGE}" \
    -o "$TMP_IMAGE"

curl \
    --fail \
    --silent \
    --location \
    "${UBUNTU_BASE_URL}/SHA256SUMS" \
    -o "$TMP_SHA"

EXPECTED_SHA="$(
    awk -v f="$UBUNTU_IMAGE" '
        $2 == f || $2 == "*"f {
            print $1
            exit
        }
    ' "$TMP_SHA"
)"

ACTUAL_SHA="$(sha256sum "$TMP_IMAGE" | awk '{print $1}')"

[[ -n "$EXPECTED_SHA" ]] \
    || die "Nie znaleziono checksum dla ${UBUNTU_IMAGE}."

if [[ "$EXPECTED_SHA" != "$ACTUAL_SHA" ]]; then
    die "SHA256 obrazu Ubuntu jest niepoprawne. Expected=${EXPECTED_SHA}, Actual=${ACTUAL_SHA}"
fi

mv "$TMP_IMAGE" "$BASE_IMAGE"

echo "Obraz Ubuntu pobrany i zweryfikowany."

# ----------------------------------------------------------------------------
# CREATE VM DISK
# ----------------------------------------------------------------------------

log "Tworzenie dysku ${VM_DISK}..."

qemu-img convert \
    -f qcow2 \
    -O qcow2 \
    "$BASE_IMAGE" \
    "$VM_DISK"

qemu-img resize "$VM_DISK" "$DISK_SIZE"

chmod 0644 "$VM_DISK"

# ----------------------------------------------------------------------------
# CLOUD-INIT
# ----------------------------------------------------------------------------

log "Tworzenie konfiguracji cloud-init..."

WORKDIR="$(mktemp -d)"

cleanup_all() {
    rm -rf "$WORKDIR" 2>/dev/null || true
    cleanup_tmp
}
trap cleanup_all EXIT

cat > "${WORKDIR}/meta-data" <<EOF
instance-id: ${VM_NAME}
local-hostname: ${VM_NAME}
EOF

cat > "${WORKDIR}/network-config" <<EOF
version: 2

ethernets:

  factory0:

    match:
      macaddress: "${VM_MAC}"

    set-name: factory0

    dhcp4: false
    dhcp6: false

    addresses:
      - ${VM_IP}/${PREFIX}

    routes:
      - to: 0.0.0.0/0
        via: ${GATEWAY}

    nameservers:
      addresses:
        - ${DNS1}
        - ${DNS2}
EOF

cat > "${WORKDIR}/user-data" <<EOF
#cloud-config

hostname: ${VM_NAME}
fqdn: ${VM_NAME}
manage_etc_hosts: true

timezone: Europe/Warsaw

ssh_pwauth: false
disable_root: true

users:

  - name: ${VM_USER}

    gecos: Public Radar Factory

    shell: /bin/bash

    groups:
      - sudo
      - adm

    sudo:
      - ALL=(ALL) NOPASSWD:ALL

    lock_passwd: true

    ssh_authorized_keys:
      - ${PUBKEY}

package_update: true
package_upgrade: true

packages:

  - git
  - curl
  - wget
  - ca-certificates

  - jq
  - ripgrep
  - tmux
  - unzip

  - build-essential
  - pkg-config

  - python3
  - python3-dev
  - python3-pip
  - python3-venv

  - podman
  - uidmap
  - slirp4netns
  - fuse-overlayfs

  - bubblewrap

  - sqlite3
  - postgresql-client

  - qemu-guest-agent

  - ufw

write_files:

  - path: /etc/motd
    permissions: '0644'
    content: |
      ============================================================
       Public Radar Autonomous Software Factory
      ============================================================

       Hostname: ${VM_NAME}
       IP:       ${VM_IP}
       User:     ${VM_USER}

       Workspace:
         /opt/factory

      ============================================================

runcmd:

  - mkdir -p /opt/factory

  - chown -R ${VM_USER}:${VM_USER} /opt/factory

  - systemctl enable --now qemu-guest-agent

  - ufw allow OpenSSH

  - ufw --force enable

  - su - ${VM_USER} -c 'python3 -m venv /opt/factory/.venv'

  - su - ${VM_USER} -c '/opt/factory/.venv/bin/pip install --upgrade pip wheel setuptools'

  - su - ${VM_USER} -c '/opt/factory/.venv/bin/pip install openai openai-agents pydantic PyYAML'

  - su - ${VM_USER} -c 'curl -fsSL https://chatgpt.com/codex/install.sh | sh'

  - su - ${VM_USER} -c 'mkdir -p /opt/factory/factory /opt/factory/project /opt/factory/scripts /opt/factory/logs'

  - chown -R ${VM_USER}:${VM_USER} /opt/factory

final_message: |
  ============================================================
  Public Radar Factory VM installation complete
  ============================================================

  VM:       ${VM_NAME}
  IP:       ${VM_IP}
  User:     ${VM_USER}

  Connect:
      ssh ${VM_USER}@${VM_IP}

  Workspace:
      /opt/factory
EOF

# ----------------------------------------------------------------------------
# CREATE NOCLOUD SEED ISO
# ----------------------------------------------------------------------------

log "Tworzenie NoCloud seed ISO..."

xorriso \
    -as mkisofs \
    -o "$SEED_ISO" \
    -V cidata \
    -J \
    -R \
    "${WORKDIR}/user-data" \
    "${WORKDIR}/meta-data" \
    "${WORKDIR}/network-config" \
    >/dev/null 2>&1

chmod 0644 "$SEED_ISO"

# ----------------------------------------------------------------------------
# OS VARIANT
# ----------------------------------------------------------------------------

log "Wykrywanie libosinfo..."

if virt-install --osinfo list 2>/dev/null | grep -q "ubuntu24.04"; then
    OS_VARIANT="ubuntu24.04"
else
    OS_VARIANT="generic"
fi

echo "OS variant: ${OS_VARIANT}"

# ----------------------------------------------------------------------------
# CREATE VM
# ----------------------------------------------------------------------------

log "Tworzenie VM ${VM_NAME}..."

virt-install \
    --name "$VM_NAME" \
    --memory "$RAM_MB" \
    --vcpus "$VCPUS" \
    --cpu host-passthrough \
    --virt-type kvm \
    --machine q35 \
    --disk "path=${VM_DISK},format=qcow2,bus=virtio,cache=none,discard=unmap" \
    --disk "path=${SEED_ISO},device=cdrom" \
    --os-variant "$OS_VARIANT" \
    --network "type=direct,source=${HOST_IF},source_mode=bridge,model=virtio,mac=${VM_MAC}" \
    --graphics none \
    --console pty,target_type=serial \
    --channel unix,target_type=virtio,name=org.qemu.guest_agent.0 \
    --import \
    --noautoconsole

virsh autostart "$VM_NAME"

# ----------------------------------------------------------------------------
# SHOW DOMAIN NETWORK
# ----------------------------------------------------------------------------

log "Konfiguracja interfejsu VM..."

virsh domiflist "$VM_NAME" || true

# ----------------------------------------------------------------------------
# WAIT FOR GUEST
# ----------------------------------------------------------------------------

log "Czekam, aż VM zacznie odpowiadać na ${VM_IP}..."

PING_OK=0

for _ in $(seq 1 120); do
    if ping -c 1 -W 1 "$VM_IP" >/dev/null 2>&1; then
        PING_OK=1
        break
    fi
    sleep 2
done

# ----------------------------------------------------------------------------
# FINAL OUTPUT
# ----------------------------------------------------------------------------

echo
echo "=============================================================================="
echo " Public Radar Factory VM"
echo "=============================================================================="
echo
echo " VM            : ${VM_NAME}"
echo " OS            : Ubuntu Server ${UBUNTU_RELEASE} LTS"
echo " vCPU          : ${VCPUS}"
echo " RAM           : ${RAM_MB} MB"
echo " Disk          : ${DISK_SIZE}"
echo
echo " Network       : Direct / macvtap"
echo " Host IF       : ${HOST_IF}"
echo " Mode          : bridge"
echo " VM IP         : ${VM_IP}/${PREFIX}"
echo " Gateway       : ${GATEWAY}"
echo " MAC           : ${VM_MAC}"
echo
echo " User          : ${VM_USER}"
echo " Workspace     : /opt/factory"
echo

if [[ "$PING_OK" -eq 1 ]]; then
    echo " VM odpowiada na ping."
else
    echo " VM jeszcze nie odpowiedziała na ping."
    echo " Cloud-init i pierwszy upgrade systemu mogą nadal trwać."
fi

echo
echo "Połącz się:"
echo
echo "    ssh ${VM_USER}@${VM_IP}"
echo
echo "Następnie:"
echo
echo "    cloud-init status --wait"
echo "    codex --version"
echo "    python3 --version"
echo "    podman --version"
echo
echo "Python environment:"
echo
echo "    source /opt/factory/.venv/bin/activate"
echo
echo "    python -c \"import agents; print('Agents SDK OK')\""
echo
echo "Libvirt:"
echo
echo "    virsh dominfo ${VM_NAME}"
echo "    virsh domiflist ${VM_NAME}"
echo "    virsh console ${VM_NAME}"
echo
echo "=============================================================================="
echo
echo "UWAGA:"
echo "Przy libvirt Direct/macvtap VM może nie komunikować się bezpośrednio"
echo "z samym hypervisorem przez ${HOST_IF}. Komunikacja z pozostałą siecią LAN"
echo "powinna działać normalnie."
echo "=============================================================================="
