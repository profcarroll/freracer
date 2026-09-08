#!/bin/sh
# Push freracer from the laptop to the N900. Run from the repo root:
#
#   sh tools/deploy.sh
#   N900_HOST=root@10.0.0.71 sh tools/deploy.sh     # if DHCP moved it
#
# This is the "atoms" half of the rule: it copies bytes a human has already
# read onto the device, and it does not run anything there. To actually play,
# tap freracer in the app grid, or:
#
#   n900 'cd /home/user/MyDocs/freracer && DISPLAY=:0 python2.5 game.py'
#
# The desktop launcher (desktop/install.sh) is a separate, one-time step that
# runs ON the device as root; it only needs re-running if desktop/ changes.
set -e

HOST=${N900_HOST:-root@10.0.0.70}
DEST=${N900_DEST:-/home/user/MyDocs/freracer}

# The laptop's OpenSSL 3.5 refuses the N900's ssh-rsa/legacy KEX and cipher
# suite outright ("error in libcrypto") without a config that lowers the
# security level. ~/.local/bin/n900 already carries these options, but it
# wraps ssh only - scp needs them passed directly, because they do not
# propagate through a ProxyCommand.
OPENSSL_CONF="$HOME/.ssh/n900-openssl-legacy.cnf"
export OPENSSL_CONF
OPTS="-i $HOME/.ssh/id_n900 -o IdentitiesOnly=yes"
OPTS="$OPTS -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa"
OPTS="$OPTS -o KexAlgorithms=+diffie-hellman-group14-sha1"
OPTS="$OPTS -o Ciphers=+aes128-cbc,3des-cbc -o MACs=+hmac-sha1"
OPTS="$OPTS -o ConnectTimeout=15"

# Only what Python 2.5 on the device actually runs. tools/generate_track.py
# (talks to sld-cloud) and tools/render_shot.py + tools/fake_pygame.py (the
# off-device renderer) are Python 3 and stay on the laptop.
GAME="game.py track.py rng.py regions.py journey.py window.py telemetry.py bot_steer.py buzz_helper.py test_track.py test_journey.py synth.py music.py"

echo "-> $HOST:$DEST"
ssh $OPTS "$HOST" "mkdir -p $DEST/tracks $DEST/tools $DEST/desktop"
scp $OPTS $GAME "$HOST:$DEST/"
scp $OPTS tracks/*.trk tracks/FORMAT.md "$HOST:$DEST/tracks/"
scp $OPTS tools/racer_fps.py tools/journey_dump.py tools/journey_export.py "$HOST:$DEST/tools/"
scp $OPTS desktop/freracer desktop/freracer.desktop desktop/freracer.png \
         desktop/install.sh "$HOST:$DEST/desktop/"

echo
echo "deployed. next, on the device:"
echo "  n900 'cd $DEST && python2.5 test_track.py'"
echo "  n900 'cd $DEST && python2.5 test_journey.py --quick'"
echo "  n900 'cd $DEST && DISPLAY=:0 python2.5 tools/racer_fps.py 15 120'"
echo "  n900 'cd $DEST && DISPLAY=:0 python2.5 tools/racer_fps.py 60 --journey 4471'"
