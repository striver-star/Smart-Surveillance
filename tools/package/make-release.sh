#!/usr/bin/env bash
# Build a release bundle for sites without internet access (Phase 9).
#   tools/package/make-release.sh 1.0.0
# Writes dist/hss-<version>/ with: the code (git archive of HEAD), images.tar.gz (every container image,
# built here), the Wall Agent builds if present, SHA256SUMS, and INSTALL.txt. Copy the folder to the
# site server and run: sudo ./install.sh --offline images.tar.gz
set -euo pipefail
VERSION=${1:?version, e.g. 1.0.0}
cd "$(dirname "$0")/../.."
[ -z "$(git status --porcelain)" ] || { echo "commit or stash your changes first (the bundle is made from HEAD)"; exit 1; }
OUT=dist/hss-$VERSION
rm -rf "$OUT"; mkdir -p "$OUT"
PROFILES="--profile ai --profile notify --profile edge --profile geo"

echo "building images..."
docker compose $PROFILES build
IMAGES=$(docker compose $PROFILES config --images | sort -u)
for img in $IMAGES; do docker image inspect "$img" >/dev/null 2>&1 || docker pull "$img"; done
echo "saving $(echo "$IMAGES" | wc -l) images..."
docker save $IMAGES | gzip -1 > "$OUT/images.tar.gz"

echo "code..."
git archive --format=tar HEAD | tar xf - -C "$OUT"
echo "$VERSION $(git rev-parse HEAD)" > "$OUT/VERSION"
[ -d dist/wall-agent ] && cp -r dist/wall-agent "$OUT/wall-agent"

cat > "$OUT/INSTALL.txt" <<TXT
HSS $VERSION offline install

1. Check the bundle:      sha256sum -c SHA256SUMS
2. Install Docker from the OS media if the server has none (packages docker.io, docker-compose-v2, docker-buildx).
3. Install:               sudo ./install.sh --offline images.tar.gz
4. Open the console at https://<server address>/ and follow Getting started.

Upgrade an existing site: copy this folder over the old one (keep .env and config/), then
                          sudo ./install.sh --offline images.tar.gz
TXT
(cd "$OUT" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
echo "release: $OUT ($(du -sh "$OUT" | cut -f1))"
