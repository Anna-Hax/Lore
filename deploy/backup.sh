#!/usr/bin/env bash
# Nightly copy of every service's sqlite state to Azure Blob Storage (cron: /etc/cron.d/lore-backup, set up by azure.sh).
# The SAS token can only create and write blobs: it can't read, list or delete them, so a compromised host
# can't wipe earlier backups. Runs as the `lore` user (uid 10001) so sqlite never leaves root-owned -wal/-shm files.
# Does not back up secrets/: keep those offline yourself (RUNBOOK).
set -euo pipefail
shopt -s nullglob
. /etc/lore-backup.env  # BACKUP_URL, BACKUP_SAS
STATE=${STATE:-/opt/lore/deploy/state}
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
stamp=$(date -u +%Y-%m-%dT%H%MZ)

for db in "$STATE"/*/*.sqlite3; do
  name="$(basename "$(dirname "$db")")-$(basename "$db")"
  sqlite3 "$db" ".backup '$tmp/$name'"  # a consistent copy while the service keeps running
  gzip "$tmp/$name"
  curl -fsS -X PUT -H "x-ms-blob-type: BlockBlob" --data-binary "@$tmp/$name.gz" \
    "$BACKUP_URL/$stamp/$name.gz?$BACKUP_SAS"
done
