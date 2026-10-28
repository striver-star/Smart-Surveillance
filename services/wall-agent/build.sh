#!/usr/bin/env bash
# Build the Wall Agent for Windows and Linux, the Windows installer, and the update manifest.
# Output goes to dist/wall-agent/ at the repository root, which the platform serves at /wall-agent/.
# Needs Go 1.22+ and NSIS (makensis). Usage: services/wall-agent/build.sh 0.1.0
set -euo pipefail
VERSION=${1:?version, for example 0.1.0}
HERE=$(cd "$(dirname "$0")" && pwd)
DIST=$(cd "$HERE/../.." && pwd)/dist/wall-agent
mkdir -p "$DIST"
cd "$HERE"
go test ./...

LDFLAGS="-s -w -X main.Version=$VERSION"
WIN=hss-wall-agent-$VERSION-windows-amd64.exe
LIN=hss-wall-agent-$VERSION-linux-amd64
# -H windowsgui: no console window flashes up on the wall screen.
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -trimpath -ldflags "$LDFLAGS -H windowsgui" -o "$DIST/$WIN" .
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags "$LDFLAGS" -o "$DIST/$LIN" .

# schtasks wants the task definition in UTF-16.
iconv -f UTF-8 -t UTF-16 installer/windows/task.xml > installer/windows/task-utf16.xml
makensis -V2 -DVERSION="$VERSION" installer/windows/hss-wall-agent.nsi
rm -f installer/windows/task-utf16.xml

sha() { sha256sum "$1" | cut -d' ' -f1; }
cat > "$DIST/manifest.json" <<JSON
{
  "version": "$VERSION",
  "files": {
    "windows/amd64": {"path": "/wall-agent/$WIN", "sha256": "$(sha "$DIST/$WIN")"},
    "linux/amd64": {"path": "/wall-agent/$LIN", "sha256": "$(sha "$DIST/$LIN")"}
  },
  "installer": "/wall-agent/hss-wall-agent-setup-$VERSION.exe"
}
JSON
(cd "$DIST" && sha256sum "$WIN" "$LIN" "hss-wall-agent-setup-$VERSION.exe" > "SHA256SUMS-$VERSION")
echo "Built $VERSION in $DIST:"
ls -l "$DIST"
