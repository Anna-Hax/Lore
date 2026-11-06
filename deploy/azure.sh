#!/usr/bin/env bash
# Create Lore's host on Azure: one Ubuntu VM that runs compose.yaml behind Caddy (TLS), plus a storage
# account for nightly sqlite backups (backup.sh). This spends money: it prints the plan and asks first.
#
# Needs `az login` with a subscription allowed in $LOCATION. Override any setting with an env var:
#   SIZE=Standard_B1ms deploy/azure.sh
# Rough cost (Nov 2026): B2s ~$35/month, B1ms ~$17, plus ~$7 for disk, static IP and storage.
set -euo pipefail

RG=${RG:-lore}
LOCATION=${LOCATION:-malaysiawest}
SIZE=${SIZE:-Standard_B2s}
VM=${VM:-lore}
ADMIN=${ADMIN:-lore-admin}
DNS_LABEL=${DNS_LABEL:-lore-$(openssl rand -hex 3)}
SSH_KEY=${SSH_KEY:-$HOME/.ssh/id_ed25519.pub}
MY_IP=${MY_IP:-$(curl -fsS https://api.ipify.org)}
STORAGE=${STORAGE:-lorebak$(openssl rand -hex 4)}  # globally unique, lowercase letters and digits
DOMAIN=$DNS_LABEL.$LOCATION.cloudapp.azure.com

cat <<EOF
In subscription "$(az account show --query name -o tsv)" this creates:
  resource group  $RG in $LOCATION
  VM              $VM: $SIZE, Ubuntu 24.04, 32 GB Standard SSD, admin $ADMIN with $SSH_KEY
  public IP       static, https://$DOMAIN
  firewall        80 and 443 open to all (Caddy, Let's Encrypt); 22 only from $MY_IP
  storage         $STORAGE (Standard LRS), container "backups", write-only SAS valid 1 year
EOF
read -rp "Create these? [y/N] " ok
[[ $ok == y ]] || exit 1

az group create -n "$RG" -l "$LOCATION" -o none

az storage account create -n "$STORAGE" -g "$RG" -l "$LOCATION" --sku Standard_LRS --kind StorageV2 \
  --min-tls-version TLS1_2 --allow-blob-public-access false -o none
KEY=$(az storage account keys list -n "$STORAGE" -g "$RG" --query '[0].value' -o tsv)
az storage container create --account-name "$STORAGE" --account-key "$KEY" -n backups -o none
SAS=$(az storage container generate-sas --account-name "$STORAGE" --account-key "$KEY" -n backups \
  --permissions cw --https-only --expiry "$(date -u -d '+1 year' +%Y-%m-%dT%H:%MZ)" -o tsv)

# First boot: Docker, Caddy (Ubuntu's own packages), the lore user compose runs as, 2 GB swap, the backup cron.
CLOUD_INIT=$(mktemp)
trap 'rm -f "$CLOUD_INIT"' EXIT
cat >"$CLOUD_INIT" <<EOF
#cloud-config
package_update: true
packages: [docker.io, docker-compose-v2, caddy, sqlite3, git]
users:
  - default
  - {name: lore, uid: 10001, system: true, shell: /usr/sbin/nologin}
write_files:
  - path: /etc/systemd/system/caddy.service.d/lore.conf
    content: |
      [Service]
      Environment=LORE_DOMAIN=$DOMAIN
  - path: /etc/lore-backup.env
    permissions: "0600"
    content: |
      BACKUP_URL=https://$STORAGE.blob.core.windows.net/backups
      BACKUP_SAS='$SAS'
  - path: /etc/cron.d/lore-backup
    content: |
      30 3 * * * lore /opt/lore/deploy/backup.sh
runcmd:
  - [chown, lore, /etc/lore-backup.env]
  - [sh, -c, "fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && echo '/swapfile none swap sw 0 0' >> /etc/fstab"]
  - [usermod, -aG, docker, $ADMIN]
  - [install, -d, -o, $ADMIN, /opt/lore]
  - [systemctl, daemon-reload]
EOF

az vm create -g "$RG" -n "$VM" -l "$LOCATION" --image Ubuntu2404 --size "$SIZE" \
  --admin-username "$ADMIN" --ssh-key-values "$SSH_KEY" \
  --os-disk-size-gb 32 --storage-sku StandardSSD_LRS \
  --public-ip-sku Standard --public-ip-address-allocation static --public-ip-address-dns-name "$DNS_LABEL" \
  --nsg-rule NONE --custom-data "$CLOUD_INIT" -o none

az network nsg rule create -g "$RG" --nsg-name "${VM}NSG" -n ssh --priority 100 --protocol Tcp \
  --destination-port-ranges 22 --source-address-prefixes "$MY_IP" -o none
az network nsg rule create -g "$RG" --nsg-name "${VM}NSG" -n web --priority 110 --protocol Tcp \
  --destination-port-ranges 80 443 -o none

cat <<EOF

Done. Next (RUNBOOK.md, "Azure host"):
  ssh $ADMIN@$DOMAIN
  LORE_PUBLIC_URL=https://$DOMAIN
EOF
