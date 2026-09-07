# buzz_helper.py - tiny standalone process that turns pattern names written to
# its stdin (one per line) into MCE vibrator D-Bus calls.
#
# game.py spawns exactly one of these, early, before pygame/track surfaces are
# allocated. Forking a *this* small helper process per haptic event is cheap;
# forking the whole pygame-loaded game process per event (the first attempt)
# measurably stalled the frame loop on real N900 hardware - "freezes with
# rumbles" in playtest feedback, i.e. sustained rumble-strip contact kept
# re-triggering a fork of the big process every 0.35s.
import subprocess
import sys

DEVNULL = open('/dev/null', 'wb')


def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        name = line.strip()
        if not name:
            continue
        try:
            subprocess.call((
                'dbus-send', '--system', '--type=method_call',
                '--dest=com.nokia.mce', '/com/nokia/mce/request',
                'com.nokia.mce.request.req_vibrator_pattern_activate',
                'string:' + name,
            ), stdout=DEVNULL, stderr=DEVNULL)
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
