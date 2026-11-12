# Licence scan and SBOM (task 23)

Generated 2026-11-12 by `tools/licence-scan/scan.py`. Engineering guidance against Section 19, not legal advice.

**Result: PASS.** 242 components: 232 ok, 10 conditional.

Status meanings: **ok** permissive licence; **conditional** allowed under the condition shown (LGPL library used unmodified, GPL program run separately, or a declared exception); **waived** checked by hand, see waivers.json; **unknown** needs a manual check; **denied** not allowed.

## Native libraries inside Python wheels

- ai-worker: FFmpeg (inside opencv-python-headless): LGPL-2.1-or-later (libavcodec reports: LGPL version 2.1 or later)

## Needs attention or carries a condition

| Component | Version | Licence | Status | Why |
| --- | --- | --- | --- | --- |
| bundled: FFmpeg (inside opencv-python-headless) |  | LGPL-2.1-or-later | conditional | Allowed as an unmodified, dynamically linked library or separate process. libavcodec reports: LGPL version 2.1 or later |
| exception: Hikvision NVRs, cameras and firmware | site | Proprietary-free | conditional | A declared exception in Section 19 (free of charge, closed source, not redistributed).  (checked 2026-11-12) |
| exception: NVIDIA driver and CUDA | server | Proprietary-free | conditional | A declared exception in Section 19 (free of charge, closed source, not redistributed).  (checked 2026-11-12) |
| exception: WhatsApp network | service | Proprietary-free | conditional | A declared exception in Section 19 (free of charge, closed source, not redistributed). Unofficial client (whatsapp-web.js). WhatsApp may restrict the number; e-mail and push are the fallbacks. (checked 2026-11-12) |
| exception: Windows on the wall PCs | OEM | Proprietary-free | conditional | A declared exception in Section 19 (free of charge, closed source, not redistributed).  (checked 2026-11-12) |
| image: nvcr.io/nvidia/tensorrt | 24.08-py3 | Proprietary-free | conditional | A declared exception in Section 19 (free of charge, closed source, not redistributed). NVIDIA Deep Learning Container licence. Declared exception (Section 19): pull from NVIDIA on the server; never push the built image to a public registry or ship it to clients. Re-check NVIDIA's terms before any hosted release. (checked 2026-11-12) |
| image: postgis/postgis | 16-3.5 | PostgreSQL AND GPL-2.0-or-later | conditional | Only as a separate, unmodified service or OS package, never linked into our code. PostgreSQL is under the PostgreSQL licence; PostGIS is GPL-2.0-or-later and runs unmodified as part of the database server. Our code talks to it over the network only. (checked 2026-11-12) |
| npm: node-webpmux | 3.2.1 | LGPL-2.1-or-later | conditional | Allowed as an unmodified, dynamically linked library or separate process. |
| pypi: psycopg | 3.2.3 | LGPL-3.0-only | conditional | Allowed as an unmodified, dynamically linked library or separate process. |
| pypi: psycopg-binary | 3.2.3 | LGPL-3.0-only | conditional | Allowed as an unmodified, dynamically linked library or separate process. |

## Licences in use

| Licence | Components |
| --- | --- |
| MIT | 146 |
| ISC | 27 |
| Apache-2.0 | 23 |
| BSD-3-Clause | 15 |
| BSD-2-Clause | 6 |
| Proprietary-free | 5 |
| BlueOak-1.0.0 | 4 |
| LGPL-3.0-only | 2 |
| PSF-2.0 | 2 |
| LGPL-2.1-or-later | 2 |
| MPL-2.0 | 1 |
| Apache-2.0 OR MIT | 1 |
| BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | 1 |
| Apache-2.0 OR BSD-2-Clause | 1 |
| Python-2.0 | 1 |
| 0BSD | 1 |
| PostgreSQL AND GPL-2.0-or-later | 1 |
| OFL-1.1 | 1 |
| CC-BY-4.0 | 1 |
| Zlib | 1 |

## All components

| Type | Name | Version | Licence | Status | Used by / use |
| --- | --- | --- | --- | --- | --- |
| build-tool | Go toolchain and standard library | 1.24 | BSD-3-Clause | ok | Builds the Wall Agent; the standard library is compiled into it |
| build-tool | NSIS | 3.x | Zlib | ok | Builds the Windows Wall Agent installer |
| bundled | FFmpeg (inside opencv-python-headless) |  | LGPL-2.1-or-later | conditional | ai-worker |
| dataset | COCO 2017 (training data of the YOLOX weights) | 2017 | CC-BY-4.0 | ok | Not shipped or used by us; listed because the model weights were trained on it |
| exception | Hikvision NVRs, cameras and firmware | site | Proprietary-free | conditional | Client-owned devices, reached only through ISAPI and RTSP |
| exception | NVIDIA driver and CUDA | server | Proprietary-free | conditional | GPU driver on the AI server, installed from NVIDIA |
| exception | WhatsApp network | service | Proprietary-free | conditional | External messaging network used through a linked phone |
| exception | Windows on the wall PCs | OEM | Proprietary-free | conditional | Comes with the PC hardware |
| image | binwiederhier/ntfy | v2.11.0 | Apache-2.0 | ok | Push notification server |
| image | bluenviron/mediamtx | 1.9.3 | MIT | ok | Video gateway (RTSP to WebRTC) |
| image | caddy | 2.8.4-alpine | Apache-2.0 | ok | HTTPS reverse proxy |
| image | node | 22.12.0-bookworm-slim | MIT | ok | Base image for the WhatsApp gateway |
| image | nvcr.io/nvidia/tensorrt | 24.08-py3 | Proprietary-free | conditional | Base image for the GPU AI worker (Dockerfile.gpu), built on the client's server |
| image | postgis/postgis | 16-3.5 | PostgreSQL AND GPL-2.0-or-later | conditional | Database, separate container, unmodified |
| image | python | 3.12-slim | PSF-2.0 | ok | Base image for the API and the AI worker |
| media | OpenCV sample video vtest.avi | 4.x | Apache-2.0 | ok | Demo and tests only (fetch-models.sh --demo), never shipped |
| model | YOLOX-S and YOLOX-Nano ONNX weights | 0.1.1rc0 | Apache-2.0 | ok | Person and vehicle detection (Tier S) |
| npm | @babel/code-frame | 7.29.7 | MIT | ok | whatsapp-gateway |
| npm | @babel/helper-validator-identifier | 7.29.7 | MIT | ok | whatsapp-gateway |
| npm | @isaacs/cliui | 8.0.2 | ISC | ok | whatsapp-gateway |
| npm | @pkgjs/parseargs | 0.11.0 | MIT | ok | whatsapp-gateway |
| npm | @puppeteer/browsers | 2.13.0 | Apache-2.0 | ok | whatsapp-gateway |
| npm | @tootallnate/quickjs-emscripten | 0.23.0 | MIT | ok | whatsapp-gateway |
| npm | @types/node | 26.6.6 | MIT | ok | whatsapp-gateway |
| npm | @types/yauzl | 2.10.3 | MIT | ok | whatsapp-gateway |
| npm | abort-controller | 3.0.0 | MIT | ok | whatsapp-gateway |
| npm | agent-base | 7.1.4 | MIT | ok | whatsapp-gateway |
| npm | ansi-regex | 5.0.1 | MIT | ok | whatsapp-gateway |
| npm | ansi-regex | 6.6.0 | MIT | ok | whatsapp-gateway |
| npm | ansi-styles | 4.3.0 | MIT | ok | whatsapp-gateway |
| npm | ansi-styles | 6.2.3 | MIT | ok | whatsapp-gateway |
| npm | archiver | 7.0.1 | MIT | ok | whatsapp-gateway |
| npm | archiver-utils | 5.0.2 | MIT | ok | whatsapp-gateway |
| npm | argparse | 2.0.1 | Python-2.0 | ok | whatsapp-gateway |
| npm | ast-types | 0.13.4 | MIT | ok | whatsapp-gateway |
| npm | async | 3.2.6 | MIT | ok | whatsapp-gateway |
| npm | async | 0.2.10 | MIT | ok | whatsapp-gateway |
| npm | b4a | 1.9.0 | Apache-2.0 | ok | whatsapp-gateway |
| npm | balanced-match | 1.0.2 | MIT | ok | whatsapp-gateway |
| npm | bare-buffer | 3.7.1 | Apache-2.0 | ok | whatsapp-gateway |
| npm | bare-events | 2.9.2 | Apache-2.0 | ok | whatsapp-gateway |
| npm | bare-fs | 4.8.4 | Apache-2.0 | ok | whatsapp-gateway |
| npm | bare-path | 3.1.2 | Apache-2.0 | ok | whatsapp-gateway |
| npm | bare-stream | 2.13.4 | Apache-2.0 | ok | whatsapp-gateway |
| npm | bare-url | 2.5.6 | Apache-2.0 | ok | whatsapp-gateway |
| npm | base64-js | 1.5.1 | MIT | ok | whatsapp-gateway |
| npm | basic-ftp | 5.3.1 | MIT | ok | whatsapp-gateway |
| npm | bluebird | 3.7.2 | MIT | ok | whatsapp-gateway |
| npm | brace-expansion | 2.1.8 | MIT | ok | whatsapp-gateway |
| npm | buffer | 6.0.3 | MIT | ok | whatsapp-gateway |
| npm | buffer-crc32 | 1.0.0 | MIT | ok | whatsapp-gateway |
| npm | buffer-crc32 | 0.2.13 | MIT | ok | whatsapp-gateway |
| npm | callsites | 3.1.0 | MIT | ok | whatsapp-gateway |
| npm | camelcase | 5.3.1 | MIT | ok | whatsapp-gateway |
| npm | chromium-bidi | 14.0.0 | Apache-2.0 | ok | whatsapp-gateway |
| npm | cliui | 8.0.1 | ISC | ok | whatsapp-gateway |
| npm | cliui | 6.0.0 | ISC | ok | whatsapp-gateway |
| npm | color-convert | 2.0.1 | MIT | ok | whatsapp-gateway |
| npm | color-name | 1.1.4 | MIT | ok | whatsapp-gateway |
| npm | compress-commons | 6.0.2 | MIT | ok | whatsapp-gateway |
| npm | core-util-is | 1.0.3 | MIT | ok | whatsapp-gateway |
| npm | cosmiconfig | 9.0.2 | MIT | ok | whatsapp-gateway |
| npm | crc-32 | 1.2.2 | Apache-2.0 | ok | whatsapp-gateway |
| npm | crc32-stream | 6.0.0 | MIT | ok | whatsapp-gateway |
| npm | cross-spawn | 7.0.6 | MIT | ok | whatsapp-gateway |
| npm | data-uri-to-buffer | 6.0.2 | MIT | ok | whatsapp-gateway |
| npm | debug | 4.4.3 | MIT | ok | whatsapp-gateway |
| npm | decamelize | 1.2.0 | MIT | ok | whatsapp-gateway |
| npm | degenerator | 5.0.1 | MIT | ok | whatsapp-gateway |
| npm | devtools-protocol | 0.0.1581282 | BSD-3-Clause | ok | whatsapp-gateway |
| npm | dijkstrajs | 1.0.3 | MIT | ok | whatsapp-gateway |
| npm | duplexer2 | 0.1.4 | BSD-3-Clause | ok | whatsapp-gateway |
| npm | eastasianwidth | 0.2.0 | MIT | ok | whatsapp-gateway |
| npm | emoji-regex | 8.0.0 | MIT | ok | whatsapp-gateway |
| npm | emoji-regex | 9.2.2 | MIT | ok | whatsapp-gateway |
| npm | end-of-stream | 1.4.5 | MIT | ok | whatsapp-gateway |
| npm | env-paths | 2.2.1 | MIT | ok | whatsapp-gateway |
| npm | error-ex | 1.3.4 | MIT | ok | whatsapp-gateway |
| npm | escalade | 3.2.0 | MIT | ok | whatsapp-gateway |
| npm | escodegen | 2.1.0 | BSD-2-Clause | ok | whatsapp-gateway |
| npm | esprima | 4.0.1 | BSD-2-Clause | ok | whatsapp-gateway |
| npm | estraverse | 5.3.0 | BSD-2-Clause | ok | whatsapp-gateway |
| npm | esutils | 2.0.3 | BSD-2-Clause | ok | whatsapp-gateway |
| npm | event-target-shim | 5.0.1 | MIT | ok | whatsapp-gateway |
| npm | events | 3.3.0 | MIT | ok | whatsapp-gateway |
| npm | events-universal | 1.0.1 | Apache-2.0 | ok | whatsapp-gateway |
| npm | extract-zip | 2.0.1 | BSD-2-Clause | ok | whatsapp-gateway |
| npm | fast-fifo | 1.3.2 | MIT | ok | whatsapp-gateway |
| npm | fd-slicer | 1.1.0 | MIT | ok | whatsapp-gateway |
| npm | find-up | 4.1.0 | MIT | ok | whatsapp-gateway |
| npm | fluent-ffmpeg | 2.1.3 | MIT | ok | whatsapp-gateway |
| npm | foreground-child | 3.3.1 | ISC | ok | whatsapp-gateway |
| npm | fs-extra | 11.3.4 | MIT | ok | whatsapp-gateway |
| npm | get-caller-file | 2.0.5 | ISC | ok | whatsapp-gateway |
| npm | get-stream | 5.2.0 | MIT | ok | whatsapp-gateway |
| npm | get-uri | 6.0.5 | MIT | ok | whatsapp-gateway |
| npm | glob | 10.5.0 | ISC | ok | whatsapp-gateway |
| npm | graceful-fs | 4.2.11 | ISC | ok | whatsapp-gateway |
| npm | http-proxy-agent | 7.0.2 | MIT | ok | whatsapp-gateway |
| npm | https-proxy-agent | 7.0.6 | MIT | ok | whatsapp-gateway |
| npm | ieee754 | 1.2.1 | BSD-3-Clause | ok | whatsapp-gateway |
| npm | import-fresh | 3.3.1 | MIT | ok | whatsapp-gateway |
| npm | inherits | 2.0.4 | ISC | ok | whatsapp-gateway |
| npm | ip-address | 10.7.6 | MIT | ok | whatsapp-gateway |
| npm | is-arrayish | 0.2.1 | MIT | ok | whatsapp-gateway |
| npm | is-fullwidth-code-point | 3.0.0 | MIT | ok | whatsapp-gateway |
| npm | is-stream | 2.0.1 | MIT | ok | whatsapp-gateway |
| npm | isarray | 1.0.0 | MIT | ok | whatsapp-gateway |
| npm | isexe | 2.0.0 | ISC | ok | whatsapp-gateway |
| npm | jackspeak | 3.4.3 | BlueOak-1.0.0 | ok | whatsapp-gateway |
| npm | js-tokens | 4.0.0 | MIT | ok | whatsapp-gateway |
| npm | js-yaml | 4.3.2 | MIT | ok | whatsapp-gateway |
| npm | json-parse-even-better-errors | 2.3.1 | MIT | ok | whatsapp-gateway |
| npm | jsonfile | 6.2.1 | MIT | ok | whatsapp-gateway |
| npm | lazystream | 1.0.1 | MIT | ok | whatsapp-gateway |
| npm | lines-and-columns | 1.2.4 | MIT | ok | whatsapp-gateway |
| npm | locate-path | 5.0.0 | MIT | ok | whatsapp-gateway |
| npm | lodash | 4.18.1 | MIT | ok | whatsapp-gateway |
| npm | lru-cache | 10.4.3 | ISC | ok | whatsapp-gateway |
| npm | lru-cache | 7.18.3 | ISC | ok | whatsapp-gateway |
| npm | mime | 3.0.0 | MIT | ok | whatsapp-gateway |
| npm | minimatch | 9.0.9 | ISC | ok | whatsapp-gateway |
| npm | minimatch | 5.1.9 | ISC | ok | whatsapp-gateway |
| npm | minipass | 7.1.3 | BlueOak-1.0.0 | ok | whatsapp-gateway |
| npm | mitt | 3.0.1 | MIT | ok | whatsapp-gateway |
| npm | ms | 2.1.3 | MIT | ok | whatsapp-gateway |
| npm | netmask | 2.1.1 | MIT | ok | whatsapp-gateway |
| npm | node-fetch | 2.7.0 | MIT | ok | whatsapp-gateway |
| npm | node-int64 | 0.4.0 | MIT | ok | whatsapp-gateway |
| npm | node-webpmux | 3.2.1 | LGPL-2.1-or-later | conditional | whatsapp-gateway |
| npm | normalize-path | 3.0.0 | MIT | ok | whatsapp-gateway |
| npm | once | 1.4.0 | ISC | ok | whatsapp-gateway |
| npm | p-limit | 2.3.0 | MIT | ok | whatsapp-gateway |
| npm | p-locate | 4.1.0 | MIT | ok | whatsapp-gateway |
| npm | p-try | 2.2.0 | MIT | ok | whatsapp-gateway |
| npm | pac-proxy-agent | 7.2.0 | MIT | ok | whatsapp-gateway |
| npm | pac-resolver | 7.0.1 | MIT | ok | whatsapp-gateway |
| npm | package-json-from-dist | 1.0.1 | BlueOak-1.0.0 | ok | whatsapp-gateway |
| npm | parent-module | 1.0.1 | MIT | ok | whatsapp-gateway |
| npm | parse-json | 5.2.0 | MIT | ok | whatsapp-gateway |
| npm | path-exists | 4.0.0 | MIT | ok | whatsapp-gateway |
| npm | path-key | 3.1.1 | MIT | ok | whatsapp-gateway |
| npm | path-scurry | 1.11.1 | BlueOak-1.0.0 | ok | whatsapp-gateway |
| npm | pend | 1.2.0 | MIT | ok | whatsapp-gateway |
| npm | picocolors | 1.1.1 | ISC | ok | whatsapp-gateway |
| npm | pngjs | 5.0.0 | MIT | ok | whatsapp-gateway |
| npm | process | 0.11.10 | MIT | ok | whatsapp-gateway |
| npm | process-nextick-args | 2.0.1 | MIT | ok | whatsapp-gateway |
| npm | progress | 2.0.3 | MIT | ok | whatsapp-gateway |
| npm | proxy-agent | 6.5.0 | MIT | ok | whatsapp-gateway |
| npm | proxy-from-env | 1.1.0 | MIT | ok | whatsapp-gateway |
| npm | pump | 3.0.4 | MIT | ok | whatsapp-gateway |
| npm | puppeteer | 24.38.0 | Apache-2.0 | ok | whatsapp-gateway |
| npm | puppeteer-core | 24.38.0 | Apache-2.0 | ok | whatsapp-gateway |
| npm | qrcode | 1.5.4 | MIT | ok | whatsapp-gateway |
| npm | readable-stream | 2.3.8 | MIT | ok | whatsapp-gateway |
| npm | readable-stream | 4.8.0 | MIT | ok | whatsapp-gateway |
| npm | readdir-glob | 1.1.3 | Apache-2.0 | ok | whatsapp-gateway |
| npm | require-directory | 2.1.1 | MIT | ok | whatsapp-gateway |
| npm | require-main-filename | 2.0.0 | ISC | ok | whatsapp-gateway |
| npm | resolve-from | 4.0.0 | MIT | ok | whatsapp-gateway |
| npm | safe-buffer | 5.1.2 | MIT | ok | whatsapp-gateway |
| npm | safe-buffer | 5.2.1 | MIT | ok | whatsapp-gateway |
| npm | semver | 7.8.6 | ISC | ok | whatsapp-gateway |
| npm | set-blocking | 2.0.0 | ISC | ok | whatsapp-gateway |
| npm | shebang-command | 2.0.0 | MIT | ok | whatsapp-gateway |
| npm | shebang-regex | 3.0.0 | MIT | ok | whatsapp-gateway |
| npm | signal-exit | 4.1.0 | ISC | ok | whatsapp-gateway |
| npm | smart-buffer | 4.2.0 | MIT | ok | whatsapp-gateway |
| npm | socks | 2.8.10 | MIT | ok | whatsapp-gateway |
| npm | socks-proxy-agent | 8.0.5 | MIT | ok | whatsapp-gateway |
| npm | source-map | 0.6.1 | BSD-3-Clause | ok | whatsapp-gateway |
| npm | streamx | 2.28.1 | MIT | ok | whatsapp-gateway |
| npm | string-width | 4.2.3 | MIT | ok | whatsapp-gateway |
| npm | string-width | 5.1.2 | MIT | ok | whatsapp-gateway |
| npm | string_decoder | 1.1.1 | MIT | ok | whatsapp-gateway |
| npm | string_decoder | 1.3.0 | MIT | ok | whatsapp-gateway |
| npm | strip-ansi | 6.0.1 | MIT | ok | whatsapp-gateway |
| npm | strip-ansi | 7.2.0 | MIT | ok | whatsapp-gateway |
| npm | tar-fs | 3.1.3 | MIT | ok | whatsapp-gateway |
| npm | tar-stream | 3.2.2 | MIT | ok | whatsapp-gateway |
| npm | teex | 1.0.1 | MIT | ok | whatsapp-gateway |
| npm | text-decoder | 1.2.7 | Apache-2.0 | ok | whatsapp-gateway |
| npm | tr46 | 0.0.3 | MIT | ok | whatsapp-gateway |
| npm | tslib | 2.9.1 | 0BSD | ok | whatsapp-gateway |
| npm | typed-query-selector | 2.12.3 | MIT | ok | whatsapp-gateway |
| npm | undici-types | 8.9.0 | MIT | ok | whatsapp-gateway |
| npm | universalify | 2.0.1 | MIT | ok | whatsapp-gateway |
| npm | unzipper | 0.12.3 | MIT | ok | whatsapp-gateway |
| npm | util-deprecate | 1.0.2 | MIT | ok | whatsapp-gateway |
| npm | webdriver-bidi-protocol | 0.4.1 | Apache-2.0 | ok | whatsapp-gateway |
| npm | webidl-conversions | 3.0.1 | BSD-2-Clause | ok | whatsapp-gateway |
| npm | whatsapp-web.js | 1.34.8 | Apache-2.0 | ok | whatsapp-gateway |
| npm | whatwg-url | 5.0.0 | MIT | ok | whatsapp-gateway |
| npm | which | 2.0.2 | ISC | ok | whatsapp-gateway |
| npm | which | 1.3.1 | ISC | ok | whatsapp-gateway |
| npm | which-module | 2.0.1 | ISC | ok | whatsapp-gateway |
| npm | wrap-ansi | 7.0.0 | MIT | ok | whatsapp-gateway |
| npm | wrap-ansi | 6.2.0 | MIT | ok | whatsapp-gateway |
| npm | wrap-ansi | 8.1.0 | MIT | ok | whatsapp-gateway |
| npm | wrappy | 1.0.2 | ISC | ok | whatsapp-gateway |
| npm | ws | 8.22.2 | MIT | ok | whatsapp-gateway |
| npm | y18n | 5.0.8 | ISC | ok | whatsapp-gateway |
| npm | y18n | 4.0.3 | ISC | ok | whatsapp-gateway |
| npm | yargs | 17.7.3 | MIT | ok | whatsapp-gateway |
| npm | yargs | 15.4.1 | MIT | ok | whatsapp-gateway |
| npm | yargs-parser | 21.1.1 | ISC | ok | whatsapp-gateway |
| npm | yargs-parser | 18.1.3 | ISC | ok | whatsapp-gateway |
| npm | yauzl | 2.10.0 | MIT | ok | whatsapp-gateway |
| npm | zip-stream | 6.0.1 | MIT | ok | whatsapp-gateway |
| npm | zod | 3.25.76 | MIT | ok | whatsapp-gateway |
| os-package | chromium (Debian bookworm) | distribution | BSD-3-Clause | ok | Headless browser run by whatsapp-web.js, separate process |
| os-package | fonts-liberation | distribution | OFL-1.1 | ok | Fonts for headless Chromium |
| pypi | annotated-types | 0.8.0 | MIT | ok | api |
| pypi | anyio | 4.16.0 | MIT | ok | ai-worker, api, probe |
| pypi | certifi | 2026.10.23 | MPL-2.0 | ok | ai-worker, api, probe |
| pypi | click | 8.5.1 | BSD-3-Clause | ok | api |
| pypi | fastapi | 0.115.6 | MIT | ok | api |
| pypi | flatbuffers | 25.12.19 | Apache-2.0 | ok | ai-worker |
| pypi | h11 | 0.16.0 | MIT | ok | ai-worker, api, probe |
| pypi | httpcore | 1.0.9 | BSD-3-Clause | ok | ai-worker, api, probe |
| pypi | httptools | 0.9.0 | MIT | ok | api |
| pypi | httpx | 0.28.1 | BSD-3-Clause | ok | ai-worker, api, probe |
| pypi | idna | 3.20 | BSD-3-Clause | ok | ai-worker, api, probe |
| pypi | numpy | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | ok | ai-worker |
| pypi | onnxruntime | 1.29.0 | MIT | ok | ai-worker |
| pypi | opencv-python-headless | 5.0.0.93 | Apache-2.0 | ok | ai-worker |
| pypi | packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | ok | ai-worker |
| pypi | protobuf | 7.36.2 | BSD-3-Clause | ok | ai-worker |
| pypi | psycopg | 3.2.3 | LGPL-3.0-only | conditional | api |
| pypi | psycopg-binary | 3.2.3 | LGPL-3.0-only | conditional | api |
| pypi | pydantic | 2.14.3 | MIT | ok | api |
| pypi | pydantic-core | 2.50.4 | MIT | ok | api |
| pypi | python-dotenv | 1.2.4 | BSD-3-Clause | ok | api |
| pypi | pyyaml | 6.0.3 | MIT | ok | api |
| pypi | starlette | 0.41.3 | BSD-3-Clause | ok | api |
| pypi | typing-extensions | 4.16.0 | PSF-2.0 | ok | ai-worker, api, probe |
| pypi | typing-inspection | 0.4.5 | MIT | ok | api |
| pypi | uvicorn | 0.34.0 | BSD-3-Clause | ok | api |
| pypi | uvloop | 0.23.0 | Apache-2.0 OR MIT | ok | api |
| pypi | watchfiles | 1.3.0 | MIT | ok | api |
| pypi | websockets | 17.4 | BSD-3-Clause | ok | api |
