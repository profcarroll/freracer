# test_journey.py - the infinite road's offline test. Python 2.5 and 3.
#
#   python3 test_journey.py              # spec-sized: 500 seeds x 300 chunks of plans
#   python3 test_journey.py --quick      # 50 x 60, for a fast edit loop
#
# Plan-level checks run on every seed (cheap: no segments are built):
# determinism, chunk and stretch lengths, curves inside the region range,
# dwell inside bounds, no A->B->A except through a recurring region, every
# built region visited somewhere in the seed set, every region reachable
# from every other within 3 hops. Segment-level checks (curve jump, width
# step, altitude bounds, the window never starving as a player drives
# through it) run on a subset of seeds, and one seed is exported to a .trk
# and compared segment for segment with the live window.

import os
import sys
import tempfile

import journey
import regions
import track
import window

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools'))
import journey_export                          # noqa: E402

failures = []


def fail(msg):
    failures.append(msg)


def plan(seed, chunks):
    gen = journey.Generator(seed)
    out = []
    k = 0
    while k < chunks:
        out.append(gen.next_chunk())
        k += 1
    return gen, out


def check_plans(seed, gen, chunks):
    seen = set()
    k = 0
    while k < len(chunks):
        c = chunks[k]
        t = regions.REGIONS[c['region']]
        seen.add(c['region'])
        if c['length'] > journey.CHUNK_MAX:
            fail('seed %d chunk %d length %d > %d' % (seed, k, c['length'], journey.CHUNK_MAX))
        if c['kind'] == 'road' and c['length'] < journey.CHUNK_MIN:
            fail('seed %d chunk %d length %d < %d' % (seed, k, c['length'], journey.CHUNK_MIN))
        cmax = t['curve'][1]
        if cmax < 6.0:
            cmax = 6.0
        i = 0
        while i < len(c['stretches']):
            count, curve, hill, w = c['stretches'][i]
            if count < journey.STRETCH_MIN:
                fail('seed %d chunk %d stretch %d has %d segments' % (seed, k, i, count))
            if abs(curve) > cmax + 0.01:
                fail('seed %d chunk %d stretch %d curve %.2f out of range' % (seed, k, i, curve))
            if w != t['width']:
                fail('seed %d chunk %d stretch %d width %g != region %g' % (seed, k, i, w, t['width']))
            i += 1
        if k == 0 and (c['kind'] != 'start' or c['length'] != journey.START_STRAIGHT):
            fail('seed %d does not open with the %d-segment straight' % (seed, journey.START_STRAIGHT))
        k += 1

    # Visit sequence: dwell, and no immediate return except via RECURRING.
    visits = []
    k = 0
    while k < len(chunks):
        c = chunks[k]
        if not visits or visits[-1][0] != c['region']:
            visits.append([c['region'], 0])
        if c['kind'] != 'transition':
            visits[-1][1] += 1
        k += 1
    i = 0
    while i < len(visits):
        name, n = visits[i]
        lo, hi = regions.REGIONS[name]['dwell']
        if i < len(visits) - 1 and (n < lo or n > hi):
            fail('seed %d visit %d: %s dwelt %d chunks, bounds %d..%d' % (seed, i, name, n, lo, hi))
        if i >= 2 and visits[i][0] == visits[i - 2][0] and visits[i - 2][0] not in regions.RECURRING:
            # Forbidden unless the middle region had nowhere else to go,
            # which the Phase 1 three-region subset forces for farmland.
            alternatives = successors(visits[i - 1][0]) - set([visits[i][0]])
            if alternatives:
                fail('seed %d: %s -> %s -> %s immediate return' % (
                    seed, visits[i - 2][0], visits[i - 1][0], visits[i][0]))
        i += 1
    if gen.rerolls > len(chunks) // 4:
        fail('seed %d rerolled %d times over %d chunks' % (seed, gen.rerolls, len(chunks)))
    return seen


def check_determinism(seed, chunks):
    _, a = plan(seed, chunks)
    _, b = plan(seed, chunks)
    k = 0
    while k < chunks:
        if a[k]['stretches'] != b[k]['stretches'] or a[k]['obstacles'] != b[k]['obstacles'] \
                or a[k]['region'] != b[k]['region']:
            fail('seed %d chunk %d differs between two runs' % (seed, k))
            return
        k += 1


def successors(name):
    """Built successors of a region, unbuilt ones collapsed onto STAND_IN,
    self removed - the same view journey.py takes of the chain."""
    out = set()
    for target, w in regions.SUCCESSORS[name]:
        if target not in regions.REGIONS:
            target = regions.STAND_IN
        if target != name and target in regions.REGIONS:
            out.add(target)
    return out


def check_reachable():
    """Every built region reaches every other within 3 hops of the chain,
    with unbuilt successors collapsed onto STAND_IN as journey.py does."""
    names = sorted(regions.REGIONS.keys())
    succ = {}
    i = 0
    while i < len(names):
        succ[names[i]] = successors(names[i])
        i += 1
    i = 0
    while i < len(names):
        frontier = set([names[i]])
        reached = set([names[i]])
        hops = 0
        while hops < 3:
            nxt = set()
            for n in frontier:
                nxt |= succ[n]
            reached |= nxt
            frontier = nxt
            hops += 1
        j = 0
        while j < len(names):
            if names[j] not in reached:
                fail('%s cannot reach %s within 3 hops' % (names[i], names[j]))
            j += 1
        i += 1


def check_segments(seed, chunks):
    """Expand through the window as a player would drive it."""
    win = window.journey(seed)
    z = 0.0
    step = 6000.0 / 22.0                       # MAX_SPEED at 22 fps
    ymin = 1e9
    ymax = -1e9
    prev_base = 0
    target = chunks * journey.CHUNK_MAX
    while win.gen.k < chunks or int(z / track.SEGMENT_LENGTH) < win.gen.seg - window.LOOKAHEAD:
        if int(z / track.SEGMENT_LENGTH) > target:
            break
        z += step
        if win.feed(z):
            fail('seed %d: window starved at segment %d' % (seed, int(z / track.SEGMENT_LENGTH)))
            return
        win.trim(z)
        if win.base < prev_base:
            fail('seed %d: base went backwards' % seed)
        prev_base = win.base
        if win.ahead(z) < track.DRAW_DISTANCE:
            fail('seed %d: only %d segments ahead at %d' % (seed, win.ahead(z), int(z / 100)))
            return
        behind = int(z / track.SEGMENT_LENGTH) - win.base
        if behind > window.KEEP_BEHIND + window.TRIM_BATCH:
            fail('seed %d: %d segments kept behind the player' % (seed, behind))
        errs = track.validate_segments(win.segments[-60:], win.base + len(win.segments) - 60)
        if errs:
            fail('seed %d: %s' % (seed, errs[0]))
            return
        y = win.segments[-1]['y']
        if y < ymin:
            ymin = y
        if y > ymax:
            ymax = y
        i = 0
        while i < len(win.obstacles):
            ob = win.obstacles[i]
            if ob[0] < win.base or ob[1] < -1.0 or ob[1] > 1.0 or ob[2] not in track.OBSTACLE_TYPES:
                fail('seed %d: bad obstacle %r' % (seed, ob))
            i += 1
    if ymin < regions.ALTITUDE_MIN or ymax > regions.ALTITUDE_MAX:
        fail('seed %d: altitude %.0f..%.0f outside %g..%g' % (
            seed, ymin, ymax, regions.ALTITUDE_MIN, regions.ALTITUDE_MAX))


def check_export(seed, chunks):
    fd, path = tempfile.mkstemp(suffix='.trk')
    os.close(fd)
    try:
        f = open(path, 'w')
        try:
            f.write('\n'.join(journey_export.export_lines(seed, chunks)) + '\n')
        finally:
            f.close()
        trk = track.load(path)
        errs = track.validate(trk)
        if errs:
            fail('export seed %d: %s' % (seed, errs[0]))
            return
        win = window.Window(journey.Generator(seed))
        win.feed(0.0, 100000)
        while win.gen.k < chunks:
            win.feed((len(win.segments) - 1) * track.SEGMENT_LENGTH, 100000)
        n = trk['finish_segment']
        if n > len(win.segments):
            fail('export seed %d: %d segments in .trk, window has %d' % (seed, n, len(win.segments)))
        i = 0
        while i < n and i < len(win.segments):
            a = trk['segments'][i]
            b = win.segments[i]
            if abs(a['curve'] - b['curve']) > 1e-6 or abs(a['y'] - b['y']) > 1e-3 \
                    or abs(a['width'] - b['width']) > 1e-6:
                fail('export seed %d: segment %d differs (%r vs %r)' % (seed, i, a, b))
                return
            i += 1
        # The window may have expanded past `chunks` to fill its lookahead;
        # compare only what lies before the exported FINISH.
        mine = 0
        i = 0
        while i < len(win.obstacles):
            if win.obstacles[i][0] < n:
                mine += 1
            i += 1
        if len(trk['obstacles']) != mine:
            fail('export seed %d: %d obstacles in .trk, window has %d' % (
                seed, len(trk['obstacles']), mine))
    finally:
        os.remove(path)


def main(argv):
    seeds = 500
    chunks = 300
    seg_seeds = 20
    seg_chunks = 60
    if '--quick' in argv:
        seeds = 50
        chunks = 60
        seg_seeds = 5
        seg_chunks = 30

    check_reachable()

    seen = set()
    seed = 1
    while seed <= seeds:
        gen, plans = plan(seed, chunks)
        seen |= check_plans(seed, gen, plans)
        seed += 1
    for name in sorted(regions.REGIONS.keys()):
        if name not in seen:
            fail('region %s never visited in %d seeds' % (name, seeds))

    seed = 1
    while seed <= 10:
        check_determinism(seed * 7919, chunks)
        seed += 1

    seed = 1
    while seed <= seg_seeds:
        check_segments(seed * 31, seg_chunks)
        seed += 1

    check_export(4471, 8)
    check_export(1, 3)

    if failures:
        sys.stdout.write('FAIL: %d problems\n' % len(failures))
        i = 0
        while i < len(failures) and i < 40:
            sys.stdout.write('  - %s\n' % failures[i])
            i += 1
        return 1
    sys.stdout.write('PASS: %d seeds x %d chunks planned, %d seeds x %d chunks driven, export round-trips\n' % (
        seeds, chunks, seg_seeds, seg_chunks))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
