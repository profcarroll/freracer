#!/bin/sh
# Build the Maemo 5 (fremantle) .deb. Run from anywhere:
#
#   sh packaging/build-deb.sh            # -> dist/freracer_<version>-1_all.deb
#   DEB_REVISION=2 sh packaging/build-deb.sh
#
# Needs only dpkg-deb and coreutils. It does NOT need dpkg-dev, fakeroot or
# a Maemo SDK: freracer is pure Python 2.5, so the package is Architecture:
# all and there is nothing to cross-compile.
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
cd "$ROOT"

VERSION=$(cat VERSION)
REV=${DEB_REVISION:-1}
ARCH=all
FULLVER="$VERSION-$REV"
OUT="dist/freracer_${FULLVER}_${ARCH}.deb"
STAGE="dist/stage/freracer_${FULLVER}_${ARCH}"

rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" \
         "$STAGE/opt/freracer/tracks" \
         "$STAGE/opt/freracer/tools" \
         "$STAGE/usr/bin" \
         "$STAGE/usr/share/applications/hildon" \
         "$STAGE/usr/share/icons/hicolor/64x64/hildon" \
         dist

# Exactly what Python 2.5 on the device runs - the same list tools/deploy.sh
# copies. The Python 3 tools (generate_track.py, render_shot.py,
# fake_pygame.py) are laptop-side and are deliberately not packaged.
GAME="game.py track.py rng.py regions.py journey.py window.py telemetry.py
      bot_steer.py buzz_helper.py test_track.py test_journey.py"
for f in $GAME; do
    install -m 644 "$f" "$STAGE/opt/freracer/$f"
done
install -m 644 tracks/*.trk tracks/FORMAT.md "$STAGE/opt/freracer/tracks/"
install -m 644 tools/racer_fps.py tools/journey_dump.py tools/journey_export.py \
        "$STAGE/opt/freracer/tools/"
install -m 644 README.md LICENSE "$STAGE/opt/freracer/"

install -m 755 desktop/freracer "$STAGE/usr/bin/freracer"
install -m 644 desktop/freracer.desktop \
        "$STAGE/usr/share/applications/hildon/freracer.desktop"
install -m 644 desktop/freracer.png \
        "$STAGE/usr/share/icons/hicolor/64x64/hildon/freracer.png"

install -m 755 packaging/postinst "$STAGE/DEBIAN/postinst"
install -m 755 packaging/postrm "$STAGE/DEBIAN/postrm"

SIZE=$(du -sk "$STAGE" | cut -f1)
sed -e "s/@VERSION@/$FULLVER/" -e "s/@ARCH@/$ARCH/" -e "s/@INSTALLED_SIZE@/$SIZE/" \
    packaging/control.in > "$STAGE/DEBIAN/control"

# XB-Maemo-Icon-26 is how the Application manager gets an icon for a package
# it has not installed yet: a base64 PNG carried in the control field itself,
# as a continuation block (every line indented by one space).
printf 'XB-Maemo-Icon-26:\n' >> "$STAGE/DEBIAN/control"
base64 packaging/freracer-48.png | sed -e 's/^/ /' >> "$STAGE/DEBIAN/control"

# -Zgzip is not optional. The N900's dpkg is 1.14.25 and predates xz; a
# default modern .deb dies there with "contains ununderstood data member
# control.tar.xz, giving up". --root-owner-group avoids needing fakeroot.
dpkg-deb -Zgzip --root-owner-group --build "$STAGE" "$OUT" >/dev/null

echo "$OUT"
