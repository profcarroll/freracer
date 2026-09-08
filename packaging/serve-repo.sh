#!/bin/sh
# Serve dist/repo to an N900 on the same Wi-Fi, as a Maemo application
# catalogue. Builds the .deb and the repo first if they are not there yet.
#
#   sh packaging/serve-repo.sh          # port 8000
#   PORT=8080 sh packaging/serve-repo.sh
#
# This is the shape that actually works in 2026: the N900's OpenSSL is
# 0.9.8n and cannot complete a TLS 1.2 handshake, so the device cannot talk
# to github.com, raw.githubusercontent.com or a GitHub Pages site at all.
# GitHub holds the release; a plain-HTTP host on the LAN (or any plain-HTTP
# server you control) is what the device installs from.
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
cd "$ROOT"

PORT=${PORT:-8000}

IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<NF;i++) if($i=="src") print $(i+1)}')
[ -n "$IP" ] || IP=$(ipconfig getifaddr en0 2>/dev/null || true)
[ -n "$IP" ] || IP=localhost

ls dist/freracer_*.deb >/dev/null 2>&1 || sh packaging/build-deb.sh >/dev/null
sh packaging/build-repo.sh "http://$IP:$PORT/" >/dev/null

cat <<EOF
Serving dist/repo on http://$IP:$PORT/

On the N900, Application manager -> menu title -> Application catalogues -> New:

  Catalogue name   freracer
  Web address      http://$IP:$PORT/
  Distribution     fremantle
  Components       free

Save, let it refresh, then install freracer from the Download list. Later
releases show up under Update once you re-run this script with a newer .deb.

  "fremantle" has one e. A "freemantle" typo 404s every refresh.
  Maemo will say the catalogue is not authenticated; it is unsigned, which
  is expected - answer y to "install without verification".

Or, from the device's browser: http://$IP:$PORT/freracer.install
Ctrl-C to stop.
EOF

cd dist/repo
exec python3 -m http.server "$PORT" --bind 0.0.0.0
