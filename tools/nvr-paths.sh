#!/usr/bin/env bash
# Print gateway camera lines for every channel of one NVR, plus the matching wall-test URL.
# Usage: HSS_NVR_USER=viewer HSS_NVR_PASSWORD=... tools/nvr-paths.sh nvr1 192.168.1.64 [32]
# Append the output to gateway/cameras.env (never commit that file).
set -euo pipefail
name=${1:?NVR name, e.g. nvr1}; ip=${2:?NVR IP address}; channels=${3:-32}
user=${HSS_NVR_USER:?set HSS_NVR_USER}; pass=${HSS_NVR_PASSWORD:?set HSS_NVR_PASSWORD}
enc() { python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"; }
u=$(enc "$user"); p=$(enc "$pass")
paths=()
for ch in $(seq 1 "$channels"); do
  path=$(printf '%s-ch%02d' "$name" "$ch")
  # Channel N sub-stream is N02 (low bandwidth, for grids). Pulled only while someone watches.
  echo "MTX_PATHS_${path^^}_SOURCE=rtsp://$u:$p@$ip:554/Streaming/Channels/${ch}02"
  echo "MTX_PATHS_${path^^}_SOURCEONDEMAND=yes"
  paths+=("$path")
done
echo "# wall test: https://SERVER/wall-test/?n=$channels&paths=$(IFS=,; echo "${paths[*]}")" >&2
