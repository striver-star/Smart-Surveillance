#!/usr/bin/env bash
# Restore an HSS backup.
#
#   tools/backup/hss-restore.sh --test [file]   restore the database into a scratch database, check it,
#                                               drop it (live system untouched); latest backup if no file
#   tools/backup/hss-restore.sh --full <file>   replace the live database and API data with the backup
#                                               (asks for confirmation; stops the API meanwhile)
# Run a --test at least monthly; the console's Security page shows when it last passed.
# Restore test monthly, in crontab -e:   15 3 1 * * cd ~/Smart-Surveillance && tools/backup/hss-restore.sh --test >> ~/hss-backup.log 2>&1
set -euo pipefail
umask 077
cd "$(dirname "$0")/../.."
[ -f .env ] && set -a && . ./.env && set +a
DIR=${HSS_BACKUP_DIR:-/var/backups/hss}
PASSFILE=${HSS_BACKUP_PASSFILE:-$HOME/.hss-backup-pass}
MODE=${1:-}; FILE=${2:-$(ls -1t "$DIR"/hss-*.tar.enc 2>/dev/null | head -1)}
[ "$MODE" = "--test" ] || [ "$MODE" = "--full" ] || { sed -n 2,9p "$0"; exit 2; }
[ -f "$FILE" ] || { echo "no backup file found (looked in $DIR)"; exit 1; }
NAME=$(basename "$FILE" .tar.enc)

report() {
  docker compose exec -T api python - "$1" "$2" "$NAME" <<'PY' >/dev/null 2>&1 || true
import json, os, sys, urllib.request
body = json.dumps({"kind": "restore_test", "status": sys.argv[1], "detail": sys.argv[2], "name": sys.argv[3]}).encode()
req = urllib.request.Request("http://localhost:8000/system/backup-status", data=body, method="POST",
                             headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["HSS_WORKER_TOKEN"]})
urllib.request.urlopen(req, timeout=10)
PY
}
fail() { echo "restore FAILED: $1" >&2; [ "$MODE" = "--test" ] && report failed "$1"; exit 1; }

if [ -f "$FILE.sha256" ]; then
  (cd "$(dirname "$FILE")" && sha256sum -c --quiet "$(basename "$FILE").sha256") || fail "$FILE does not match its SHA-256: damaged or changed"
fi
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass "file:$PASSFILE" -in "$FILE" | tar xf - -C "$WORK" || fail "can't decrypt (wrong passphrase?)"
(cd "$WORK/$NAME" && sha256sum -c --quiet SHA256SUMS) || fail "files inside the backup don't match their checksums"

if [ "$MODE" = "--test" ]; then
  T=hss_restore_test
  docker compose exec -T db sh -c "dropdb -U \"\$POSTGRES_USER\" --if-exists $T && createdb -U \"\$POSTGRES_USER\" $T" || fail "can't create the scratch database"
  docker compose exec -T db sh -c "pg_restore -U \"\$POSTGRES_USER\" -d $T --no-owner" < "$WORK/$NAME/database.dump" || fail "pg_restore reported errors"
  q() { docker compose exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d $1 -tAc \"$2\"" | tr -d '[:space:]'; }
  checks=""
  for t in users events alerts evidence nvrs schema_migrations; do
    n=$(q $T "SELECT count(*) FROM $t" 2>/dev/null || echo missing)
    [ "$n" = "missing" ] && [ "$t" != "evidence" ] && [ "$t" != "nvrs" ] && { docker compose exec -T db dropdb -U "$POSTGRES_USER" $T; fail "table $t missing from the restored database"; }
    checks="$checks $t=$n"
  done
  admins=$(q $T "SELECT count(*) FROM users WHERE role='admin' AND NOT disabled")
  docker compose exec -T db sh -c "dropdb -U \"\$POSTGRES_USER\" $T"
  [ "$admins" -ge 1 ] || fail "restored database has no active administrator"
  tar tzf "$WORK/$NAME/api-data.tgz" >/dev/null || fail "API data archive unreadable"
  files=$(tar tzf "$WORK/$NAME/api-data.tgz" | grep -c -v '/$' || true)
  echo "restore test OK: $NAME:$checks, $files data files"
  report ok "$NAME restored to a scratch database:$checks; $files data files readable"
  exit 0
fi

echo "This replaces the LIVE database and API data with $NAME. Everything since that backup is lost."
read -r -p "Type RESTORE to continue: " answer
[ "$answer" = "RESTORE" ] || { echo "cancelled"; exit 1; }
docker compose stop api edge traccar 2>/dev/null || true
docker compose exec -T db sh -c 'dropdb -U "$POSTGRES_USER" --force "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' < "$WORK/$NAME/database.dump"
docker compose run --rm --no-deps -T --entrypoint sh api -c 'find /data -mindepth 1 -delete; tar xzf - -C /data' < "$WORK/$NAME/api-data.tgz"
if [ -f "$WORK/$NAME/proxy-ca.tgz" ]; then
  docker compose run --rm --no-deps -T --entrypoint sh proxy -c 'tar xzf - -C /data' < "$WORK/$NAME/proxy-ca.tgz"
fi
echo "config files from the backup are in config.tgz; restore them by hand if needed: $WORK kept as $HOME/$NAME-config.tgz"
cp "$WORK/$NAME/config.tgz" "$HOME/$NAME-config.tgz"
docker compose up -d
echo "restore done from $NAME"
