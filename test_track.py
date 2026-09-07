# test_track.py - load and validate the example track, print PASS/FAIL.
# Python 2.5 safe: no print(), plain string ops only.

import sys
import track

TRACK_PATH = 'tracks/001-autumn-hills.trk'


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else TRACK_PATH
    trk = track.load(path)
    errors = track.validate(trk)

    if errors:
        print 'FAIL: %s' % path
        for e in errors:
            print '  - %s' % e
    else:
        print 'PASS: %s (%s, %d segments, lap %.0f units)' % (
            path, trk['name'], len(trk['segments']), trk['lap_length'])


if __name__ == '__main__':
    main()
