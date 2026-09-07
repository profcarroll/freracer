#!/bin/sh
# Installs the freracer Hildon desktop launcher. Run ON the device, as root,
# with the freracer repo already present (this session deploys it to
# /home/user/MyDocs/freracer over scp; see README.md "Deploying to the N900").
#
#   n900 'sh /home/user/MyDocs/freracer/desktop/install.sh'
#
set -e
HERE=$(cd "$(dirname "$0")" && pwd)

install -m 755 "$HERE/freracer" /usr/bin/freracer
install -m 644 "$HERE/freracer.desktop" /usr/share/applications/hildon/freracer.desktop
install -m 644 "$HERE/freracer.png" /usr/share/icons/hicolor/64x64/hildon/freracer.png

gtk-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
update-desktop-database /usr/share/applications >/dev/null 2>&1 || true

echo "installed: /usr/bin/freracer, freracer.desktop, freracer.png"
echo "freracer should now appear in the Hildon app grid (under Games)."
echo "if not, reboot or restart hildon-desktop to force a menu rescan."
