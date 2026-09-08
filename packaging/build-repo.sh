#!/bin/sh
# Build a Maemo 5 apt repository (an "application catalogue") around the .deb,
# so an N900 can install AND update freracer through the Application manager
# instead of a hand-copied file.
#
#   sh packaging/build-repo.sh                       # -> dist/repo/
#   sh packaging/build-repo.sh http://10.0.0.66:8000/
#
# The argument is the base URL the repo will be served from; it only affects
# the generated freracer.install one-click file, so the tree can be rebased
# later by re-running this or by editing that one file.
#
# No dpkg-scanpackages / apt-ftparchive: a Packages index is just each .deb's
# control file plus Filename/Size/checksums, and Release is a list of the
# index files with their checksums. Doing it by hand keeps this buildable on
# any machine with dpkg-deb and coreutils.
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
cd "$ROOT"

BASE_URI=${1:-http://localhost:8000/}
case "$BASE_URI" in */) ;; *) BASE_URI="$BASE_URI/" ;; esac

DIST=fremantle
COMP=free
ARCH=armel          # the device's arch; Architecture: all packages are
                    # listed in the binary-<arch> index, as in any Debian repo
REPO=dist/repo
POOL="pool/$DIST/$COMP"
INDEXDIR="dists/$DIST/$COMP/binary-$ARCH"

sum() { # sum <algo> <file>  -> bare digest, GNU or BSD
    if command -v "${1}sum" >/dev/null 2>&1; then "${1}sum" "$2" | cut -d' ' -f1
    else openssl dgst "-$1" "$2" | sed 's/.*= *//'; fi
}

DEBS=$(ls dist/freracer_*.deb 2>/dev/null || true)
if [ -z "$DEBS" ]; then
    echo "no .deb in dist/ - run packaging/build-deb.sh first" >&2
    exit 1
fi

rm -rf "$REPO"
mkdir -p "$REPO/$POOL" "$REPO/$INDEXDIR"

PACKAGES="$REPO/$INDEXDIR/Packages"
: > "$PACKAGES"
for deb in $DEBS; do
    name=$(basename "$deb")
    cp "$deb" "$REPO/$POOL/$name"
    # dpkg-deb -I <deb> control prints the control file verbatim, which is
    # what preserves the multi-line XB-Maemo-Icon-26 block the Application
    # manager reads to show an icon for a not-yet-installed package.
    dpkg-deb -I "$deb" control | sed -e '/^[[:space:]]*$/d' >> "$PACKAGES"
    {
        echo "Filename: $POOL/$name"
        echo "Size: $(wc -c < "$deb" | tr -d ' ')"
        echo "MD5sum: $(sum md5 "$deb")"
        echo "SHA1: $(sum sha1 "$deb")"
        echo "SHA256: $(sum sha256 "$deb")"
        echo
    } >> "$PACKAGES"
done
gzip -9 -n -c "$PACKAGES" > "$PACKAGES.gz"

RELEASE="$REPO/dists/$DIST/Release"
{
    echo "Origin: freracer"
    echo "Label: freracer"
    echo "Suite: $DIST"
    echo "Codename: $DIST"
    echo "Date: $(LC_ALL=C date -u '+%a, %d %b %Y %H:%M:%S UTC')"
    echo "Architectures: $ARCH all"
    echo "Components: $COMP"
    echo "Description: freracer for Maemo 5 (fremantle)"
    for algo in md5 sha1 sha256; do
        case $algo in
            md5) echo "MD5Sum:" ;; sha1) echo "SHA1:" ;; sha256) echo "SHA256:" ;;
        esac
        for f in "$COMP/binary-$ARCH/Packages" "$COMP/binary-$ARCH/Packages.gz"; do
            p="$REPO/dists/$DIST/$f"
            echo " $(sum $algo "$p") $(wc -c < "$p" | tr -d ' ') $f"
        done
    done
} > "$RELEASE"

# Maemo one-click install file. Tapping this in the device's browser opens
# the Application manager, which adds the catalogue and installs the package.
# The .install mime type (application/x-install-instructions) is registered
# to hildon-application-manager on a stock Maemo 5 device.
cat > "$REPO/freracer.install" <<EOF
[install]
catalogues = freracer
package = freracer

[freracer]
name = freracer
uri = $BASE_URI
dist = $DIST
components = $COMP
EOF

echo "$REPO  (uri $BASE_URI)"
