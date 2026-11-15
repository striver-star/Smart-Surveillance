#!/usr/bin/env bash
# HSS backup: database, API data (evidence vault, plans, branding, vault key, clips, snapshots),
# the proxy's certificate authority, and the site config files, in one encrypted file.
#
# Usage (from the project folder, as a user in the docker group):
#   tools/backup/hss-backup.sh                  # back up now
#   tools/backup/hss-backup.sh --no-media       # skip snapshots and clips (smaller)
# Settings (environment or .env):
#   HSS_BACKUP_DIR         where backups go (default /var/backups/hss)
#   HSS_BACKUP_PASSFILE    file holding the encryption passphrase (default ~/.hss-backup-pass, chmod 600)
#   HSS_BACKUP_KEEP        how many backups to keep (default 14)
#   HSS_BACKUP_COPY_TO     optional second place (NAS or USB mount) to copy each backup to
# Daily at 01:30, in crontab -e:
#   30 1 * * * cd ~/Smart-Surveillance && tools/backup/hss-backup.sh >> ~/hss-backup.log 2>&1
set -euo pipefail
umask 077
cd "$(dirname "$0")/../.."
[ -f .env ] && set -a && . ./.env && set +a
DIR=${HSS_BACKUP_DIR:-/var/backups/hss}
PASSFILE=${HSS_BACKUP_PASSFILE:-$HOME/.hss-backup-pass}
KEEP=${HSS_BACKUP_KEEP:-14}
MEDIA=1; [ "${1:-}" = "--no-media" ] && MEDIA=0
STAMP=$(date +%Y%m%d-%H%M)
NAME="hss-$STAMP"
started=$(date +%s)

report() {   # status to the platform, shown on the console's Security page
  local status=$1 detail=$2 size=${3:-0} sha=${4:-}
  docker compose exec -T api python - "$status" "$detail" "$size" "$sha" "$NAME" <<'PY' >/dev/null 2>&1 || true
import json, os, sys, urllib.request
status, detail, size, sha, name = sys.argv[1:6]
body = json.dumps({"kind": "backup", "status": status, "detail": detail, "size_bytes": int(size), "sha256": sha, "name": name}).encode()
req = urllib.request.Request("http://localhost:8000/system/backup-status", data=body, method="POST",
                             headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["HSS_WORKER_TOKEN"]})
urllib.request.urlopen(req, timeout=10)
PY
}
fail() { echo "backup FAILED: $1" >&2; report failed "$1"; exit 1; }

[ -s "$PASSFILE" ] || fail "no passphrase file $PASSFILE (create it: openssl rand -base64 32 > $PASSFILE && chmod 600 $PASSFILE, and keep a copy offline)"
[ "$(stat -c %a "$PASSFILE")" = "600" ] || chmod 600 "$PASSFILE"
mkdir -p "$DIR" || fail "can't create $DIR (run: sudo mkdir -p $DIR && sudo chown $USER $DIR)"
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/$NAME"

echo "database..."
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$WORK/$NAME/database.dump" || fail "pg_dump failed"
[ -s "$WORK/$NAME/database.dump" ] || fail "database dump is empty"

echo "API data..."
EXCL=""; [ $MEDIA = 0 ] && EXCL="--exclude=./snapshots --exclude=./clips"
docker compose exec -T api sh -c "tar czf - -C /data $EXCL ." > "$WORK/$NAME/api-data.tgz" || fail "API data copy failed"

echo "certificate authority..."
docker compose exec -T proxy sh -c 'tar czf - -C /data caddy/pki' > "$WORK/$NAME/proxy-ca.tgz" 2>/dev/null || echo "  (proxy CA not found; skipped)"

echo "config..."
tar czf "$WORK/$NAME/config.tgz" --ignore-failed-read .env config gateway/cameras.env gps 2>/dev/null || true
git rev-parse HEAD > "$WORK/$NAME/version.txt" 2>/dev/null || true
(cd "$WORK/$NAME" && sha256sum ./* > SHA256SUMS)

echo "encrypting..."
tar cf - -C "$WORK" "$NAME" | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "file:$PASSFILE" -out "$DIR/$NAME.tar.enc" \
  || fail "encryption failed"
SHA=$(sha256sum "$DIR/$NAME.tar.enc" | cut -d' ' -f1)
echo "$SHA  $NAME.tar.enc" > "$DIR/$NAME.tar.enc.sha256"
SIZE=$(stat -c %s "$DIR/$NAME.tar.enc")

if [ -n "${HSS_BACKUP_COPY_TO:-}" ]; then
  cp "$DIR/$NAME.tar.enc" "$DIR/$NAME.tar.enc.sha256" "$HSS_BACKUP_COPY_TO/" || fail "copy to $HSS_BACKUP_COPY_TO failed"
fi
ls -1t "$DIR"/hss-*.tar.enc 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do rm -f "$old" "$old.sha256"; done

secs=$(( $(date +%s) - started ))
echo "backup OK: $DIR/$NAME.tar.enc ($((SIZE / 1048576)) MB, ${secs}s)"
report ok "$((SIZE / 1048576)) MB in ${secs}s${HSS_BACKUP_COPY_TO:+, copied to $HSS_BACKUP_COPY_TO}" "$SIZE" "$SHA"
