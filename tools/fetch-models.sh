#!/usr/bin/env bash
# Download the open-source models (and the demo video) with checksum checks.
# YOLOX weights: Apache 2.0, Megvii. Demo video: OpenCV sample data (Apache 2.0).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p models demo/media

fetch() {  # url target sha256
  if [ -f "$2" ] && echo "$3  $2" | sha256sum -c --quiet 2>/dev/null; then
    echo "ok       $2"; return
  fi
  echo "download $2"
  curl -fsSL --retry 3 -o "$2.part" "$1"
  echo "$3  $2.part" | sha256sum -c --quiet
  mv "$2.part" "$2"
}

YOLOX=https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0
fetch $YOLOX/yolox_s.onnx    models/yolox_s.onnx    c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063
fetch $YOLOX/yolox_nano.onnx models/yolox_nano.onnx c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d

if [ "${1:-}" = "--demo" ]; then
  fetch https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/vtest.avi demo/media/vtest.avi \
        45cddc9490be69345cbdab64ca583be65987e864ca408038e648db99e10516cf
fi
