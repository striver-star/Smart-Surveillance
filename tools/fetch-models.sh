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

# Face and plate recognition (task 18). OpenCV Zoo YuNet (MIT) and SFace (Apache 2.0).
ZOO=https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models
fetch $ZOO/face_detection_yunet/face_detection_yunet_2023mar.onnx models/face_detection_yunet_2023mar.onnx \
      8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4
fetch $ZOO/face_recognition_sface/face_recognition_sface_2021dec.onnx models/face_recognition_sface_2021dec.onnx \
      0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79
# PaddleOCR PP-OCRv4 detection and recognition (Apache 2.0), taken from the RapidOCR wheel on PyPI.
if [ ! -f models/ch_PP-OCRv4_rec_infer.onnx ] || [ ! -f models/ch_PP-OCRv4_det_infer.onnx ]; then
  fetch https://files.pythonhosted.org/packages/ba/12/1e5497183bdbe782dbb91bad1d0d2297dba4d2831b2652657f7517bfc6df/rapidocr_onnxruntime-1.4.4-py3-none-any.whl \
        models/rapidocr-1.4.4.whl 971d7d5f223a7a808662229df1ef69893809d8457d834e6373d3854bc1782cbf
  python3 -I -c 'import sys, zipfile; z = zipfile.ZipFile(sys.argv[1]); [open("models/" + n.split("/")[-1], "wb").write(z.read(n)) for n in z.namelist() if n.endswith(("PP-OCRv4_det_infer.onnx", "PP-OCRv4_rec_infer.onnx"))]' models/rapidocr-1.4.4.whl
  rm -f models/rapidocr-1.4.4.whl
fi
echo "d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9  models/ch_PP-OCRv4_det_infer.onnx" | sha256sum -c --quiet
echo "48fc40f24f6d2a207a2b1091d3437eb3cc3eb6b676dc3ef9c37384005483683b  models/ch_PP-OCRv4_rec_infer.onnx" | sha256sum -c --quiet
echo "ok       models/ch_PP-OCRv4_det_infer.onnx, models/ch_PP-OCRv4_rec_infer.onnx"

if [ "${1:-}" = "--demo" ]; then
  fetch https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/vtest.avi demo/media/vtest.avi \
        45cddc9490be69345cbdab64ca583be65987e864ca408038e648db99e10516cf
  # Two OpenCV sample photos, used only by the face tests (never shipped).
  fetch https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/lena.jpg demo/media/lena.jpg \
        7de7ed51a1594fff247f4cae2301eceacf5313d6011e37b4a4c8733f7bb72c07
  fetch https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/messi5.jpg demo/media/messi5.jpg \
        1d570e49654e84c7a943918537bd9e5e1ef82920152e147c834006e235be97c9
fi
