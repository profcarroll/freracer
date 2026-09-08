"""Write the first N chunks of a journey as a finite .trk.

    python3 tools/journey_export.py --seed 4471 --chunks 6 --out tracks/901-seed-4471.trk

The exported file goes through the same expander as the live window
(track.expand_stretch), so it is the same road segment for segment, which
lets the existing validator, test_track.py, bot runs and racer_fps.py
exercise generated road with no new tooling. It also gives a good journey
slice a home: a drive a human liked is exported and kept.

Region tags are dropped; THEME is the first region. Width changes between
regions become WIDTH lines between ROAD lines (see tracks/FORMAT.md).
Python 2.5 and 3 both run this.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

import journey                                 # noqa: E402
import track                                   # noqa: E402

SEGMENTS_PER_SECOND = 60.0                     # MAX_SPEED / SEGMENT_LENGTH


def export_lines(seed, chunks):
    gen = journey.Generator(seed)
    lines = ['# Journey seed %d, first %d chunks (tools/journey_export.py)' % (seed, chunks)]
    body = []
    width = None
    total = 0
    first_region = None
    k = 0
    while k < chunks:
        c = gen.next_chunk()
        if first_region is None:
            first_region = c['region']
        body.append('# chunk %d: %s %s (%s)' % (c['id'], c['region'], c['motif'], c['kind']))
        i = 0
        while i < len(c['stretches']):
            count, curve, hill, w = c['stretches'][i]
            if width is None:
                width = w
                lines.append('WIDTH %g' % w)
            elif w != width:
                body.append('WIDTH %g' % w)
                width = w
            body.append('ROAD %d %.12g %.12g' % (count, curve, hill))
            i += 1
        i = 0
        while i < len(c['obstacles']):
            local, offset, kind = c['obstacles'][i]
            body.append('OBSTACLE %d %.4f %s' % (c['start'] + local, offset, kind))
            i += 1
        total += c['length']
        k += 1
    head = ['NAME Journey %d' % seed,
            'THEME %s' % first_region,
            'SEED %d' % seed,
            'PAR %d' % int(total / SEGMENTS_PER_SECOND * 1.3 + 1)]
    return [lines[0]] + head + lines[1:] + body + ['FINISH %d' % total]


def main(argv):
    seed = 1
    chunks = 6
    out = None
    i = 1
    while i < len(argv):
        if argv[i] == '--seed':
            seed = int(argv[i + 1])
        elif argv[i] == '--chunks':
            chunks = int(argv[i + 1])
        elif argv[i] == '--out':
            out = argv[i + 1]
        else:
            sys.stderr.write(__doc__)
            return 2
        i += 2
    if out is None:
        out = 'tracks/9%02d-seed-%d.trk' % (seed % 100, seed)

    text = '\n'.join(export_lines(seed, chunks)) + '\n'
    tmp = out + '.candidate'
    f = open(tmp, 'w')
    try:
        f.write(text)
    finally:
        f.close()
    trk = track.load(tmp)
    errors = track.validate(trk)
    if errors:
        i = 0
        while i < len(errors):
            sys.stdout.write(errors[i] + '\n')
            i += 1
        os.remove(tmp)
        return 1
    os.rename(tmp, out)
    sys.stdout.write('%s: %s, %d segments, par %g\n' % (
        out, trk['name'], trk['finish_segment'], trk['par']))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
