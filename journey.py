# journey.py - the infinite road's generator: region chain + parametric chunks.
# Python 2.5 safe, same output on Python 3 (everything random goes through rng.Rng).
#
# A Generator is created once from an integer seed and asked for chunks in
# order. A chunk is a plan, not road: a list of ROAD stretches
# (segments, curve, hill, width_end) plus obstacles at chunk-local segment
# indices. window.py expands the plan into segment dicts with
# track.expand_stretch, a stretch at a time, just ahead of the camera.
# tools/journey_export.py writes the same plans out as a finite .trk, and
# because both paths go through the same expander they produce the same
# segments - which is what makes the laptop a valid test of the device.
#
# Chunk k depends only on (seed, k, the generator's state at k), and that
# state is itself a pure function of the seed, so a journey replays exactly.
# Nothing in here reads the clock or the frame rate.

import regions
import rng

CHUNK_MIN = 150          # segments; shorter recipes get a straight appended
CHUNK_MAX = 450
STRETCH_MIN = 10
START_STRAIGHT = 120     # first chunk: easy road for the tilt calibration window
TRANSITION_LENGTH = 150  # Phase 1 transition: a straight that ramps the width
NOISE_WAVELENGTH = 160.0 # segments per terrain-noise lattice point
FOLLOW = 0.5             # how much of the gap to the terrain target a stretch closes
MAX_REROLLS = 8


class Generator(object):

    def __init__(self, seed, table=None):
        self.seed = int(seed)
        self.table = table or regions.REGIONS
        self.names = sorted(self.table.keys())   # deterministic iteration order
        self.k = 0                     # chunks emitted
        self.seg = 0                   # absolute segment index of the next chunk
        self.y = 0.0
        self.width = None
        self.region = None
        self.visits = []               # region names in visit order
        self.dwell = 0                 # road chunks left in this region
        self.last_motif = None
        self.rerolls = 0
        self.chunk_log = []            # (abs_seg_start, region, chunk_id, motif, kind)

    # ---- region chain ---------------------------------------------------

    def _enter(self, name, r):
        self.region = name
        self.visits.append(name)
        lo, hi = self.table[name]['dwell']
        self.dwell = r.pick(lo, hi + 1)
        self.last_motif = None

    def _successor_weights(self, cur):
        """Successor (name, weight) pairs for `cur`, filtered to built regions.

        Unbuilt targets collapse onto STAND_IN; a region never succeeds
        itself; the previous region is excluded unless it may recur; anything
        visited within VARIETY_WINDOW has its weight halved. Weights are kept
        as integers (x2) so the halving stays exact.
        """
        weights = {}
        i = 0
        succ = regions.SUCCESSORS.get(cur, ())
        while i < len(succ):
            name, w = succ[i]
            if name not in self.table:
                name = regions.STAND_IN
            if name in self.table and name != cur:
                weights[name] = weights.get(name, 0) + w * 2
            i += 1
        prev = None
        if len(self.visits) >= 2:
            prev = self.visits[-2]
        if prev is not None and prev in weights and prev not in regions.RECURRING \
                and len(weights) > 1:
            del weights[prev]
        recent = self.visits[-regions.VARIETY_WINDOW:]
        out = []
        i = 0
        names = sorted(weights.keys())
        while i < len(names):
            w = weights[names[i]]
            if names[i] in recent:
                w = w // 2
            if w < 1:
                w = 1
            out.append((names[i], w))
            i += 1
        if not out:
            i = 0
            while i < len(self.names):
                if self.names[i] != cur:
                    out.append((self.names[i], 1))
                i += 1
        return out

    def _first_region(self, r):
        openers = []
        i = 0
        while i < len(regions.OPENERS):
            if regions.OPENERS[i] in self.table:
                openers.append((regions.OPENERS[i], 1))
            i += 1
        if not openers:
            openers = [(self.names[0], 1)]
        return r.weighted(openers)

    # ---- terrain --------------------------------------------------------

    def terrain(self, seg, region):
        """Target altitude at an absolute segment: value noise inside the band."""
        lo, hi = self.table[region]['altitude']
        n = rng.noise(self.seed, seg / NOISE_WAVELENGTH)
        return lo + (hi - lo) * (0.5 + 0.5 * n)

    def _add_terrain(self, stretches, region, amp=None):
        """Fold the terrain noise into each stretch's hill and carry y.

        A motif's own hill (a crest, a switchback's climb) is kept; on top of
        it each stretch closes FOLLOW of the gap to the terrain target at its
        end, clamped to the region's amplitude. That bounds long-run drift
        (the target lives in the region's altitude band) and gives the road
        rolling ground that continues across chunk boundaries.
        """
        if amp is None:
            amp = self.table[region]['hill'][1]
        seg = self.seg
        y = self.y
        out = []
        i = 0
        while i < len(stretches):
            count, curve, hill, w = stretches[i]
            seg += count
            target = self.terrain(seg, region)
            total = hill + (target - (y + hill)) * FOLLOW
            if total > amp:
                total = amp
            elif total < -amp:
                total = -amp
            out.append((count, curve, total, w))
            y += total
            i += 1
        return out

    # ---- motif recipes (spec 4.6) ----------------------------------------

    def _recipe(self, motif, region, r):
        t = self.table[region]
        w = t['width']
        slo, shi = t['straight']
        clo, chi = t['curve']
        hlo, hhi = t['hill']
        L = r.pick(slo, shi + 1)
        c = r.uniform(clo, chi) * r.sign()
        h = r.uniform(hlo, hhi)
        if motif == 'straight':
            return [(L, 0.0, 0.0, w)]
        if motif == 'sweeper':
            q = L // 4
            if q < STRETCH_MIN:
                q = STRETCH_MIN
            return [(q, 0.0, 0.0, w), (L, c, 0.0, w), (q, 0.0, 0.0, w)]
        if motif == 'esses':
            e = L // 2
            if e < STRETCH_MIN:
                e = STRETCH_MIN
            return [(e, c, 0.0, w), (e, -c, 0.0, w), (e, c * 0.8, 0.0, w)]
        if motif == 'crest':
            d = L // 2
            if d < STRETCH_MIN:
                d = STRETCH_MIN
            return [(L, 0.0, h, w), (d, 0.0, -h * 0.3, w)]
        if motif == 'hairpin':
            return self._hairpin(c, w)
        if motif == 'switchback':
            climb = r.uniform(hlo, hhi) * 0.6
            return (self._hairpin(c, w) + [(25, 0.0, climb, w)] +
                    self._hairpin(-c, w) + [(25, 0.0, climb, w)])
        if motif == 'descent':
            return [(L, c * 0.5, -h, w), (L, -c * 0.5, -h, w)]
        if motif == 'meander':
            out = []
            n = r.pick(3, 6)
            sign = r.sign()
            i = 0
            while i < n:
                out.append((r.pick(slo, shi + 1), r.uniform(1.5, 3.0) * sign, 0.0, w))
                sign = -sign
                i += 1
            return out
        if motif == 'corner':
            return self._corner(c, w)
        if motif == 'main-street':
            return ([(30, 0.0, 0.0, w)] + self._corner(c, w) +
                    [(60, 0.0, 0.0, w)] + self._corner(c * r.sign(), w))
        return [(L, 0.0, 0.0, w)]

    def _hairpin(self, c, w):
        # Spec recipe: ROAD 40 0 0 (braking zone); ROAD 30 5..6 0; ROAD 30 0 0
        mag = abs(c)
        if mag < 5.0:
            mag = 5.0
        elif mag > 6.0:
            mag = 6.0
        if c < 0:
            mag = -mag
        return [(40, 0.0, 0.0, w), (30, mag, 0.0, w), (30, 0.0, 0.0, w)]

    def _corner(self, c, w):
        if c > 0:
            c = 6.0
        else:
            c = -6.0
        return [(15, 0.0, 0.0, w), (12, c, 0.0, w), (15, 0.0, 0.0, w)]

    # ---- chunks ---------------------------------------------------------

    def _pick_motif(self, region, r):
        t = self.table[region]
        items = []
        i = 0
        while i < len(t['motifs']):
            name, w = t['motifs'][i]
            if name == self.last_motif and not t['repeat_motif'] and len(t['motifs']) > 1:
                w = 0
            items.append((name, w))
            i += 1
        return r.weighted(items)

    def _obstacles(self, stretches, region, r):
        """Obstacles on straight stretches only, at the region's rate."""
        t = self.table[region]
        kinds = t['obstacles']
        out = []
        if not kinds:
            return out
        seg = 0
        i = 0
        while i < len(stretches):
            count, curve, hill, w = stretches[i]
            if curve == 0.0 and count >= 30:
                # rate is per 1000 segments; roll per stretch
                if r.pick(0, 1000) < t['obstacle_rate'] * count:
                    local = seg + r.pick(10, count - 10)
                    offset = r.uniform(-0.7, 0.7)
                    out.append((local, offset, kinds[r.pick(0, len(kinds))]))
            seg += count
            i += 1
        return out

    def _check(self, chunk, region):
        """Static validation of a plan (spec 4.4 step 5). Returns an error or ''."""
        t = self.table[region]
        chi = t['curve'][1] + 0.01
        if chi < 6.01:
            chi = 6.01   # hairpin/corner recipes are fixed at 5..6
        total = 0
        i = 0
        while i < len(chunk['stretches']):
            count, curve, hill, w = chunk['stretches'][i]
            if count < STRETCH_MIN:
                return 'stretch %d shorter than %d' % (i, STRETCH_MIN)
            if curve > chi or curve < -chi:
                return 'stretch %d curve %.2f outside region range' % (i, curve)
            total += count
            i += 1
        if total > CHUNK_MAX:
            return 'chunk length %d over %d' % (total, CHUNK_MAX)
        if chunk['kind'] == 'road' and total < CHUNK_MIN:
            return 'chunk length %d under %d' % (total, CHUNK_MIN)
        i = 0
        while i < len(chunk['obstacles']):
            local, offset, kind = chunk['obstacles'][i]
            if local < 0 or local >= total:
                return 'obstacle %d outside chunk' % local
            i += 1
        return ''

    def _plan(self, r):
        """One candidate chunk plan from the current state. Pure of side effects
        except for consuming r."""
        if self.k == 0:
            region = self.region
            w = self.table[region]['width']
            stretches = [(START_STRAIGHT, 0.0, 0.0, w)]
            chunk = {'kind': 'start', 'motif': 'straight', 'region': region,
                     'stretches': stretches, 'obstacles': []}
        elif self.dwell <= 0:
            nxt = r.weighted(self._successor_weights(self.region))
            w = self.table[nxt]['width']
            stretches = [(TRANSITION_LENGTH, 0.0, 0.0, w)]
            chunk = {'kind': 'transition', 'motif': 'transition', 'region': nxt,
                     'stretches': stretches, 'obstacles': []}
        else:
            region = self.region
            motif = self._pick_motif(region, r)
            stretches = self._recipe(motif, region, r)
            total = 0
            i = 0
            while i < len(stretches):
                total += stretches[i][0]
                i += 1
            if total < CHUNK_MIN:
                stretches.append((CHUNK_MIN - total, 0.0, 0.0, self.table[region]['width']))
            chunk = {'kind': 'road', 'motif': motif, 'region': region,
                     'stretches': stretches, 'obstacles': []}
            chunk['obstacles'] = self._obstacles(stretches, region, r)
        amp = None
        if chunk['kind'] == 'transition':
            # Let the transition carry the bigger of the two regions' climbs,
            # or a descent out of the mountains takes all of the next region.
            amp = self.table[self.region]['hill'][1]
            if self.table[chunk['region']]['hill'][1] > amp:
                amp = self.table[chunk['region']]['hill'][1]
        chunk['stretches'] = self._add_terrain(chunk['stretches'], chunk['region'], amp)
        return chunk

    def next_chunk(self):
        """Return the next chunk plan and advance the generator state.

        {'id', 'kind' ('start'|'road'|'transition'), 'region', 'motif',
         'start' (absolute segment), 'length', 'stretches', 'obstacles'}
        """
        r = rng.Rng(self.seed * 1000003 + self.k)
        if self.region is None:
            self._enter(self._first_region(r), r)
            self.width = self.table[self.region]['width']
        chunk = None
        tries = 0
        while tries < MAX_REROLLS:
            cand = self._plan(r)
            err = self._check(cand, cand['region'])
            if not err:
                chunk = cand
                break
            self.rerolls += 1
            tries += 1
        if chunk is None:
            # Never leave the road unbuilt: a plain straight always passes.
            w = self.width
            chunk = {'kind': 'road', 'motif': 'straight', 'region': self.region,
                     'stretches': self._add_terrain([(CHUNK_MIN, 0.0, 0.0, w)], self.region),
                     'obstacles': []}

        if chunk['kind'] == 'transition':
            self._enter(chunk['region'], r)
        elif chunk['kind'] == 'road':
            self.dwell -= 1
            self.last_motif = chunk['motif']
        else:
            self.dwell -= 1

        length = 0
        i = 0
        while i < len(chunk['stretches']):
            count, curve, hill, w = chunk['stretches'][i]
            length += count
            self.y += hill
            self.width = w
            i += 1
        chunk['id'] = self.k
        chunk['start'] = self.seg
        chunk['length'] = length
        self.chunk_log.append((self.seg, chunk['region'], self.k, chunk['motif'], chunk['kind']))
        self.seg += length
        self.k += 1
        return chunk
