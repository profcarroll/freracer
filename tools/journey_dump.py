"""Print a journey's chunk sequence as a table: the human-readable smoke test.

    python3 tools/journey_dump.py --seed 4471 --chunks 40

Columns: chunk id, kind, region, motif, start segment, length, max |curve|,
altitude at the end of the chunk, width. Python 2.5 and 3 both run this.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

import journey                                 # noqa: E402


def main(argv):
    seed = 1
    chunks = 40
    i = 1
    while i < len(argv):
        if argv[i] == '--seed':
            seed = int(argv[i + 1])
        elif argv[i] == '--chunks':
            chunks = int(argv[i + 1])
        else:
            sys.stderr.write(__doc__)
            return 2
        i += 2
    gen = journey.Generator(seed)
    sys.stdout.write('seed %d\n' % seed)
    sys.stdout.write('%4s %-10s %-10s %-11s %7s %5s %6s %7s %5s %s\n' % (
        'id', 'kind', 'region', 'motif', 'start', 'len', 'curve', 'y', 'width', 'obstacles'))
    k = 0
    while k < chunks:
        c = gen.next_chunk()
        mx = 0.0
        j = 0
        while j < len(c['stretches']):
            if abs(c['stretches'][j][1]) > mx:
                mx = abs(c['stretches'][j][1])
            j += 1
        sys.stdout.write('%4d %-10s %-10s %-11s %7d %5d %6.2f %7.0f %5.0f %d\n' % (
            c['id'], c['kind'], c['region'], c['motif'], c['start'], c['length'],
            mx, gen.y, gen.width, len(c['obstacles'])))
        k += 1
    sys.stdout.write('regions: %s\nrerolls: %d\n' % (' > '.join(gen.visits), gen.rerolls))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
