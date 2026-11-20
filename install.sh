#!/usr/bin/env bash
# HSS Security Surveillance System: installer and upgrader for Ubuntu 22.04+ and Debian 12+.
#
#   sudo ./install.sh                         install (asks a few questions)
#   sudo ./install.sh --upgrade               back up, update the code, rebuild, restart
#   sudo ./install.sh --offline images.tar.gz install without internet, from a release bundle
#   options: --profiles notify,edge,geo,ai    services to run (default notify,edge,geo)
#            --site-name "Main campus"        name on the sign-in page
#            --yes                            no questions; defaults everywhere
#
# What it does: checks the machine, installs Docker if needed, writes .env with strong random
# secrets (never "change-me"), starts the services, creates the first administrator, sets up daily
# encrypted backups and a monthly restore test, opens the firewall ports, and prints the next steps.
# Run it again at any time: it keeps an existing .env and only fills in what is missing.
set -euo pipefail
cd "$(dirname "$0")"
HERE=$(pwd)
PROFILES="notify,edge,geo"; SITE=""; YES=0; MODE=install; OFFLINE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --profiles) PROFILES=$2; shift 2 ;;
    --site-name) SITE=$2; shift 2 ;;
    --yes|-y) YES=1; shift ;;
    --upgrade) MODE=upgrade; shift ;;
    --offline) OFFLINE=$2; shift 2 ;;
    -h|--help) sed -n 2,15p "$0"; exit 0 ;;
    *) echo "unknown option $1 (see --help)"; exit 2 ;;
  esac
done

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32mok\033[0m  %s\n' "$*"; }
warn() { printf '   \033[33m!!\033[0m  %s\n' "$*"; }
die()  { printf '   \033[31mxx\033[0m  %s\n' "$*"; exit 1; }
ask()  { local q=$1 d=$2 a; if [ $YES = 1 ]; then echo "$d"; return; fi; read -r -p "   $q [$d]: " a; echo "${a:-$d}"; }
rand() { openssl rand -hex "${1:-32}"; }

[ "$(id -u)" = 0 ] || die "run with sudo: sudo ./install.sh"
OWNER=${SUDO_USER:-root}
OWNER_HOME=$(getent passwd "$OWNER" | cut -d: -f6)
COMPOSE_PROFILES=$(echo "$PROFILES" | tr ',' '\n' | sed '/^$/d' | sed 's/^/--profile /' | tr '\n' ' ')
dc() { docker compose $COMPOSE_PROFILES "$@"; }

# ------------------------------------------------------------------ upgrade
if [ $MODE = upgrade ]; then
  say "Upgrade"
  if [ -s "$OWNER_HOME/.hss-backup-pass" ]; then
    sudo -u "$OWNER" HSS_BACKUP_PASSFILE="$OWNER_HOME/.hss-backup-pass" tools/backup/hss-backup.sh && ok "backup taken first" \
      || die "backup failed; not upgrading (fix the backup or run with a manual backup first)"
  else
    warn "no backup passphrase found; upgrading without a fresh backup"
  fi
  if [ -d .git ]; then sudo -u "$OWNER" git pull --ff-only && ok "code updated to $(git rev-parse --short HEAD)"; fi
  dc up -d --build --remove-orphans
  ok "services rebuilt and restarted"
  exit 0
fi

# ------------------------------------------------------------------ checks
say "Checking this machine"
. /etc/os-release 2>/dev/null || true
case "${ID:-}" in ubuntu|debian) ok "$PRETTY_NAME" ;; *) warn "tested on Ubuntu and Debian; this is ${PRETTY_NAME:-unknown}" ;; esac
CPUS=$(nproc); MEM=$(awk '/MemTotal/ {printf "%d", $2/1048576}' /proc/meminfo); DISK=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
[ "$CPUS" -ge 4 ] && ok "$CPUS CPU cores" || warn "$CPUS CPU cores; 4 or more recommended"
[ "$MEM" -ge 8 ] && ok "${MEM} GB memory" || warn "${MEM} GB memory; 8 GB or more recommended (16 GB with AI)"
[ "$DISK" -ge 50 ] && ok "${DISK} GB free disk" || warn "${DISK} GB free disk; 50 GB or more recommended (evidence, clips, backups)"
IFACE=$(ip route show default 2>/dev/null | awk '/default/ {print $5; exit}')
IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')
case "$IFACE" in wl*) warn "the network goes over Wi-Fi ($IFACE): wire the server at 1 Gbps to the camera network before go-live" ;;
                 "") warn "no default network route found" ;; *) ok "network on $IFACE, address ${IP:-unknown}" ;; esac
command -v openssl >/dev/null || apt-get install -y openssl >/dev/null

# ------------------------------------------------------------------ docker
say "Docker"
if ! docker compose version >/dev/null 2>&1 || ! docker buildx version >/dev/null 2>&1; then
  [ -n "$OFFLINE" ] && ! command -v docker >/dev/null && die "Docker is not installed and this is an offline install: install docker.io, docker-compose-v2 and docker-buildx from the OS media first"
  apt-get update -qq
  apt-get install -y -qq docker.io docker-compose-v2 docker-buildx >/dev/null 2>&1 \
    || apt-get install -y -qq docker.io docker-compose-plugin docker-buildx-plugin >/dev/null 2>&1 \
    || die "couldn't install Docker from the OS packages; install Docker Engine with the Compose and Buildx plugins, then run this again"
  systemctl enable --now docker >/dev/null 2>&1 || true
fi
ok "$(docker --version | cut -d, -f1), $(docker compose version --short 2>/dev/null | sed 's/^/Compose /')"
if [ "$OWNER" != root ] && ! id -nG "$OWNER" | grep -qw docker; then
  usermod -aG docker "$OWNER" && ok "$OWNER added to the docker group (takes effect at the next sign-in, or run: newgrp docker)"
fi

# ------------------------------------------------------------------ .env
say "Settings (.env)"
setenv() {   # setenv KEY VALUE: set only if missing, empty, or a placeholder
  local k=$1 v=$2 cur
  cur=$(grep -E "^$k=" .env | head -1 | cut -d= -f2- || true)
  if grep -qE "^$k=" .env; then
    case "$cur" in ""|change-me*|*change-me*) sed -i "s|^$k=.*|$k=$v|" .env; echo changed ;; *) echo kept ;; esac
  else echo "$k=$v" >> .env; echo added; fi
}
NEW=0
if [ ! -f .env ]; then cp .env.example .env; NEW=1; fi
chmod 600 .env; chown "$OWNER" .env
[ -z "$SITE" ] && SITE=$(ask "Site name shown on the sign-in page" "HSS Security Platform")
TZ_NOW=$(timedatectl show -p Timezone --value 2>/dev/null || echo Africa/Lagos)
r=$(setenv HSS_TZ "$(ask "Time zone" "${TZ_NOW:-Africa/Lagos}")")
for k in POSTGRES_PASSWORD HSS_WORKER_TOKEN HSS_WALL_TOKEN HSS_WA_TOKEN; do r=$(setenv $k "$(rand 32)"); [ "$r" != kept ] && ok "$k: new random value"; done
r=$(setenv HSS_NTFY_TOPIC "hss-alerts-$(rand 8)")
if [ -n "${IP:-}" ]; then
  r=$(setenv HSS_SERVER_IP "$IP"); [ "$r" != kept ] && ok "server address $IP"
  grep -q "^HSS_HOSTNAME=localhost$" .env && sed -i "s|^HSS_HOSTNAME=localhost$|HSS_HOSTNAME=localhost, $IP|" .env
fi
[ $NEW = 1 ] && sed -i 's|^HSS_ADMIN_TOKEN=.*|HSS_ADMIN_TOKEN=|' .env
if grep -qE "^[A-Z_]+=.*change-me" .env; then warn "still a change-me value in .env: $(grep -E '^[A-Z_]+=.*change-me' .env | cut -d= -f1 | tr '\n' ' ')"; fi
ok ".env ready (only root and $OWNER can read it)"
[ -f config/recipients.json ] || { cp config/recipients.example.json config/recipients.json; chown "$OWNER" config/recipients.json; ok "config/recipients.json created from the example: put the real WhatsApp numbers in it"; }
[ -f config/worker.json ] || { cp config/worker.example.json config/worker.json; chown "$OWNER" config/worker.json; }

# ------------------------------------------------------------------ images and start
say "Starting the services ($PROFILES)"
if [ -n "$OFFLINE" ]; then
  [ -f "$OFFLINE" ] || die "$OFFLINE not found"
  docker load -i "$OFFLINE" | tail -3
  dc up -d --no-build
else
  dc up -d --build
fi
printf '   waiting for the API'
for _ in $(seq 1 60); do
  if docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" >/dev/null 2>&1; then echo; ok "API answering"; break; fi
  printf '.'; sleep 3
done
docker compose exec -T api python - "$SITE" <<'PY' >/dev/null 2>&1 || true
import sys
from psycopg.types.json import Jsonb
from app.db import connect
with connect() as conn:
    row = conn.execute("SELECT value FROM settings WHERE key = 'branding'").fetchone()
    b = row[0] if row else {"accent": "#2563eb", "logo": None}
    if not row or b.get("site_name") in (None, "", "HSS Security Platform"):
        b["site_name"] = sys.argv[1]
        conn.execute("INSERT INTO settings (key, value) VALUES ('branding', %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (Jsonb(b),))
PY

# ------------------------------------------------------------------ first administrator
say "First administrator"
ADMINS=$(docker compose exec -T api python -c "from app.db import connect; c=connect(); print(c.execute(\"SELECT count(*) FROM users WHERE role='admin'\").fetchone()[0])" 2>/dev/null | tr -dc 0-9)
if [ "${ADMINS:-0}" -gt 0 ]; then ok "an administrator exists already"
elif [ $YES = 1 ]; then warn "create one later: docker compose exec api python -m app.auth create-admin <username>"
else
  U=$(ask "Administrator username" "it.manager")
  docker compose exec api python -m app.auth create-admin "$U" || warn "not created; run later: docker compose exec api python -m app.auth create-admin $U"
fi

# ------------------------------------------------------------------ backups
say "Backups"
mkdir -p /var/backups/hss && chown "$OWNER" /var/backups/hss && chmod 700 /var/backups/hss
PASS="$OWNER_HOME/.hss-backup-pass"
if [ ! -s "$PASS" ]; then
  openssl rand -base64 32 > "$PASS"; chown "$OWNER" "$PASS"; chmod 600 "$PASS"
  ok "backup passphrase made in $PASS"
  warn "WRITE IT DOWN and keep it offline (without it no backup can be restored): $(cat "$PASS")"
else ok "backup passphrase exists"; fi
CRON=$(crontab -u "$OWNER" -l 2>/dev/null || true)
if ! echo "$CRON" | grep -q hss-backup.sh; then
  { echo "$CRON"; echo "30 1 * * * cd $HERE && tools/backup/hss-backup.sh >> $OWNER_HOME/hss-backup.log 2>&1";
    echo "15 3 1 * * cd $HERE && tools/backup/hss-restore.sh --test >> $OWNER_HOME/hss-backup.log 2>&1"; } | sed '/^$/d' | crontab -u "$OWNER" -
  ok "daily backup 01:30 and monthly restore test scheduled for $OWNER"
else ok "backups already scheduled"; fi

# ------------------------------------------------------------------ firewall
say "Firewall"
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow 443/tcp >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 8189/udp >/dev/null
  case ",$PROFILES," in *,geo,*) ufw allow 5055/tcp >/dev/null ;; esac
  case ",$PROFILES," in *,notify,*) ufw allow 8090/tcp >/dev/null ;; esac
  ok "ufw: opened 80, 443, 8189/udp$(case ",$PROFILES," in *,geo,*) echo ', 5055';; esac)$(case ",$PROFILES," in *,notify,*) echo ', 8090';; esac). Limit them to the site networks (docs/hardening.md)."
else warn "ufw is not active; see docs/hardening.md for the ports to allow"; fi

# ------------------------------------------------------------------ done
docker compose cp proxy:/data/caddy/pki/authorities/local/root.crt "$HERE/hss-root-ca.crt" >/dev/null 2>&1 && chown "$OWNER" "$HERE/hss-root-ca.crt" || true
# Also served at https://<server>/wall-agent/hss-root-ca.crt so PCs and phones can download it (it is public: no secret in it)
if [ -f "$HERE/hss-root-ca.crt" ]; then mkdir -p "$HERE/dist/wall-agent" && cp "$HERE/hss-root-ca.crt" "$HERE/dist/wall-agent/" && chown -R "$OWNER" "$HERE/dist" || true; fi
say "Done"
cat <<EOF
   Console:      https://${IP:-<server address>}/
   Certificate:  $HERE/hss-root-ca.crt, also at https://${IP:-<server address>}/wall-agent/hss-root-ca.crt
                 (install it on each PC and phone: docs/console.md)
   Next:         sign in as the administrator and follow Getting started in the console
                 (site name and logo, NVRs, event setup, wall screens, WhatsApp, backups, licence).
   Upgrade:      sudo ./install.sh --upgrade
EOF
