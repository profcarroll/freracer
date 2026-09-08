# music.py - the procedural soundtrack: a composer that writes one beat at a
# time from what the road is doing, and a stream that keeps the SDL mixer fed
# with those beats sample-accurately.
#
# Python 2.5 safe; the same code runs on Python 3 for tools/render_song.py.
# Everything random goes through rng.Rng, seeded from the journey seed and the
# bar number, so seed 4471's mountain pass has the same bassline on the laptop
# and on the device.
#
# How it fits the frame loop (see docs/SOUNDTRACK.md for the measurements):
#
#   game.py, every frame:  music.update(ctx)      ctx = music.road_context(...)
#                          music.event('hit')     one-shots, immediate
#
#   update() spends at most a few ms: it hands finished beats to the mixer
#   (Channel.play / Channel.queue, gapless), and advances the beat being
#   rendered by a step or two. A beat is rendered ~2 beats before it sounds.
#   The composer therefore reads the road *ahead* of the car - road_context()
#   looks 1.2 s down the road for "now" and 3 s for "soon" - so a hairpin's
#   drum roll starts before the hairpin, not after it.
#
# The mixer itself is nearly free; PulseAudio on the N900 is not. Any playing
# stream costs about a third of the CPU whatever its content, and only a
# 4096-sample SDL buffer keeps that from being half. MIXER_ARGS is that
# measurement; game.py passes it to pygame.mixer.pre_init.
import time

import rng
import synth

MIXER_ARGS = (synth.SR, -16, 2, 4096)
STEPS = 4                     # sixteenth-note steps per beat
MASTER = 0.42                 # final stereo gain; groups are mixed with headroom
AHEAD_BLOCKS = 1              # rendered beats kept ready beyond the queued one
PRIME_BLOCKS = 3              # beats rendered before the first frame
BUDGET_S = 0.004              # render time per frame
NOW_S = 1.2                   # road lookahead that matches the render pipeline delay
SOON_S = 3.0                  # road lookahead for anticipation (rolls, thinning)
MIN_LOOK_SEGS = 24            # lookahead floor when the car is slow

# ---- musical material --------------------------------------------------------

SCALES = {
    'major':      (0, 2, 4, 5, 7, 9, 11),
    'minor':      (0, 2, 3, 5, 7, 8, 10),
    'dorian':     (0, 2, 3, 5, 7, 9, 10),
    'mixolydian': (0, 2, 4, 5, 7, 9, 10),
    'lydian':     (0, 2, 4, 6, 7, 9, 11),
    'majpent':    (0, 2, 4, 7, 9),
    'minpent':    (0, 3, 5, 7, 10),
}

# Chords per scale as (semitones above the key, quality, weight). The first
# entry is the tonic. The progression is a walk: from any chord, the next is
# drawn by weight from the others, and every fourth bar goes home.
CHORDS = {
    'major':      ((0, 'maj', 4), (5, 'maj', 3), (7, 'maj', 3), (9, 'min', 2), (2, 'min', 1)),
    'minor':      ((0, 'min', 4), (8, 'maj', 3), (10, 'maj', 3), (5, 'min', 2), (3, 'maj', 1)),
    'dorian':     ((0, 'min', 4), (5, 'maj', 3), (10, 'maj', 2), (2, 'min', 1)),
    'mixolydian': ((0, 'maj', 4), (10, 'maj', 3), (5, 'maj', 2), (7, 'min', 1)),
    'lydian':     ((0, 'maj', 4), (2, 'maj', 3), (9, 'min', 2), (7, 'maj', 1)),
    'majpent':    ((0, 'maj', 4), (7, 'maj', 2), (9, 'min', 2), (5, 'maj', 2)),
    'minpent':    ((0, 'min', 4), (10, 'maj', 2), (5, 'min', 2), (3, 'maj', 1)),
}

# One style per region of the infinite road (regions.py / the spec's 4.3).
# A style is recognisable the way a region is: through what the rhythm
# section does, not the key alone.
#
#   bpm          base tempo; speed bends it +-8%
#   meter        beats per bar (3 = waltz)
#   scale        SCALES key
#   bass/lead/pad/arp   synth.INSTRUMENTS names (None = no such part)
#   bass_pat     BASS key            pad_mode  'hold' | 'stab' | 'waltz'
#   drums        DRUMS key           lead_range (lo, hi) midi
#   density      lead notes per bar, 0..1
#   key          semitone offset from the journey's home key
STYLES = {
    'farmland':   {'bpm': 108, 'meter': 4, 'scale': 'majpent', 'bass': 'tri', 'bass_pat': 'walk',
                   'lead': 'pulse25', 'pad': 'organ', 'pad_mode': 'hold', 'arp': None,
                   'drums': 'country', 'lead_range': (62, 81), 'density': 0.45, 'key': 0},
    'foothills':  {'bpm': 122, 'meter': 4, 'scale': 'dorian', 'bass': 'sawbass', 'bass_pat': 'drive',
                   'lead': 'square', 'pad': 'brass', 'pad_mode': 'stab', 'arp': None,
                   'drums': 'rock', 'lead_range': (60, 79), 'density': 0.55, 'key': 5},
    'mountains':  {'bpm': 138, 'meter': 4, 'scale': 'minor', 'bass': 'sawbass', 'bass_pat': 'octave',
                   'lead': 'sawlead', 'pad': None, 'pad_mode': None, 'arp': 'pulse12',
                   'drums': 'rock', 'lead_range': (64, 84), 'density': 0.5, 'key': -3},
    'coast':      {'bpm': 96, 'meter': 4, 'scale': 'lydian', 'bass': 'sinebass', 'bass_pat': 'walk',
                   'lead': 'sine', 'pad': 'organ', 'pad_mode': 'hold', 'arp': None,
                   'drums': 'bossa', 'lead_range': (64, 83), 'density': 0.35, 'key': 0},
    'highway':    {'bpm': 130, 'meter': 4, 'scale': 'mixolydian', 'bass': 'sawbass', 'bass_pat': 'octave',
                   'lead': 'sawlead', 'pad': 'brass', 'pad_mode': 'stab', 'arp': None,
                   'drums': 'rock', 'lead_range': (62, 81), 'density': 0.5, 'key': 7},
    'strip':      {'bpm': 112, 'meter': 4, 'scale': 'minpent', 'bass': 'sqbass', 'bass_pat': 'funk',
                   'lead': 'pulse25', 'pad': 'brass', 'pad_mode': 'stab', 'arp': None,
                   'drums': 'funk', 'lead_range': (60, 79), 'density': 0.5, 'key': 2},
    'small-town': {'bpm': 132, 'meter': 3, 'scale': 'major', 'bass': 'tri', 'bass_pat': 'oompah',
                   'lead': 'square', 'pad': 'organ', 'pad_mode': 'waltz', 'arp': None,
                   'drums': 'waltz', 'lead_range': (64, 83), 'density': 0.45, 'key': 5},
    'city':       {'bpm': 118, 'meter': 4, 'scale': 'minor', 'bass': 'sqbass', 'bass_pat': 'funk',
                   'lead': 'pulse25', 'pad': 'brass', 'pad_mode': 'stab', 'arp': None,
                   'drums': 'funk', 'lead_range': (60, 79), 'density': 0.6, 'key': -2},
    'valley':     {'bpm': 100, 'meter': 4, 'scale': 'major', 'bass': 'tri', 'bass_pat': 'walk',
                   'lead': 'sine', 'pad': 'organ', 'pad_mode': 'hold', 'arp': None,
                   'drums': 'soft', 'lead_range': (60, 79), 'density': 0.4, 'key': 0},
    'river':      {'bpm': 150, 'meter': 3, 'scale': 'dorian', 'bass': 'tri', 'bass_pat': 'oompah',
                   'lead': 'sine', 'pad': None, 'pad_mode': None, 'arp': 'pulse25',
                   'drums': 'soft', 'lead_range': (64, 83), 'density': 0.35, 'key': 3},
    'lake':       {'bpm': 88, 'meter': 4, 'scale': 'major', 'bass': 'sinebass', 'bass_pat': 'walk',
                   'lead': 'sine', 'pad': 'organ', 'pad_mode': 'hold', 'arp': 'pulse12',
                   'drums': 'soft', 'lead_range': (60, 79), 'density': 0.3, 'key': -5},
}
DEFAULT_STYLE = 'farmland'

# game.py's finite-track themes are regions in disguise.
THEME_STYLE = {'autumn-hills': 'farmland', 'dusk-city': 'city', 'coast': 'coast'}

HOME_KEY = 57                 # A2: bass and pad registers are built from this
BASS_RANGE = (38, 52)
PAD_RANGE = (57, 69)

# Drum patterns, one string per part, one char per sixteenth: 'x' hit,
# 'o' open hat, '.' rest. Three levels: idle, cruising, flat out. 16 chars for
# 4/4, 12 for 3/4; the beat indexes with step % len.
DRUMS = {
    'rock': (('x...x...x...x...', '................', 'x.x.x.x.x.x.x.x.'),
             ('x...x..x..x.x...', '....x.......x...', 'x.x.x.x.x.x.x.x.'),
             ('x...x..x..x.x...', '....x.......x...', 'xxxxxxxxxxxxxxxo')),
    'country': (('x.......x.......', '................', '....x.......x...'),
                ('x...x...x...x...', '....x.......x...', 'x.x.x.x.x.x.x.x.'),
                ('x...x...x...x...', '....x......x.x..', 'xxxxxxxxxxxxxxxx')),
    'funk': (('x..x....x.x.....', '....x.......x...', 'x.x.x.x.x.x.x.x.'),
             ('x..x....x.x.....', '....x.......x...', 'x.xxx.x.x.xxx.x.'),
             ('x..x..x.x.x...x.', '....x..x....x..x', 'xxxxxxxxxxxxxxxo')),
    'soft': (('x.......x.......', '................', '..x...x...x...x.'),
             ('x.......x.......', '........x.......', '..x...x...x...x.'),
             ('x...x...x...x...', '....x.......x...', 'x.x.x.x.x.x.x.x.')),
    'bossa': (('x.....x.x.....x.', '................', '..x...x...x...x.'),
              ('x.....x.x.....x.', '...x......x.....', '..x...x...x...x.'),
              ('x.....x.x.....x.', '...x..x...x..x..', 'x.x.x.x.x.x.x.x.')),
    'waltz': (('x...........', '............', '....x...x...'),
              ('x...........', '....x...x...', '....x...x...'),
              ('x.....x.....', '....x...x...', 'x.x.x.x.x.x.')),
}

# Bass patterns: per beat of the bar, a list of (step, interval, length in
# steps). Interval is semitones above the chord root; 'third' resolves by
# chord quality.
BASS = {
    'walk':   (((0, 0, 4),), ((0, 'third', 4),), ((0, 7, 4),), ((0, 'sixth', 4),)),
    'drive':  (((0, 0, 2), (2, 0, 2)),) * 4,
    'octave': (((0, 0, 2), (2, 12, 2)), ((0, 0, 2), (2, 7, 2)),
               ((0, 0, 2), (2, 12, 2)), ((0, 7, 2), (2, 12, 2))),
    'funk':   (((0, 0, 1), (3, 0, 1)), ((2, 7, 1),), ((0, 0, 1), (1, 0, 1), (3, 10, 1)), ((2, 12, 1),)),
    'oompah': (((0, 0, 4),), ((0, 7, 2),), ((0, 7, 2),)),
}

CORNER_MOTIFS = ('hairpin', 'switchback', 'corner')

GAIN = {'drum': 0.95, 'bass': 0.85, 'lead': 0.62, 'pad': 0.42, 'arp': 0.5}


# ---- helpers -----------------------------------------------------------------

def euclid(k, n, rot=0):
    """Bresenham's take on a Euclidean rhythm: k onsets spread over n steps."""
    if k <= 0:
        return []
    if k >= n:
        return list(range(n))
    out = []
    for i in range(k):
        out.append(((i * n) // k + rot) % n)
    out.sort()
    return out


def scale_note(root, scale, degree):
    n = len(scale)
    octave = degree // n
    return root + 12 * octave + scale[degree % n]


def into_range(midi, lo, hi):
    while midi < lo:
        midi += 12
    while midi > hi:
        midi -= 12
    return midi


def chord_tones(root, chord):
    off, quality = chord[0], chord[1]
    third = (quality == 'maj') and 4 or 3
    return (root + off, root + off + third, root + off + 7)


def nearest_tone(midi, tones):
    best = midi
    best_d = 99
    for t in tones:
        for octave in (-24, -12, 0, 12, 24):
            d = abs(t + octave - midi)
            if d < best_d:
                best_d = d
                best = t + octave
    return best


def style_for(name):
    """Region or theme name -> STYLES key."""
    name = THEME_STYLE.get(name, name)
    if name in STYLES:
        return name
    return DEFAULT_STYLE


# ---- the composer --------------------------------------------------------------

class Composer(object):
    """Writes one beat at a time. State is musical (bar, chord, phrase), the
    input is the road (ctx), the output is a list of note/drum events."""

    def __init__(self, seed, region):
        self.seed = int(seed)
        self.region = None
        self.style_name = None
        self.style = None
        self.root = HOME_KEY
        self.scale = SCALES['major']
        self.chords = CHORDS['major']
        self.chord = self.chords[0]
        self.bar = 0
        self.beat = 0
        self.beats_written = 0
        self.phrases = {}
        self.deg_lo = 0
        self.deg_hi = 10
        self.intensity = 1
        self.arp_i = 0
        self.hit_rest = 0             # bars the lead sits out after a hit
        self.tension = 0              # beats of corner build-up played so far
        self.in_corner = 0
        self.crash_pending = 0
        self.thin = 0
        self.pending_region = None
        self.warm = []                # (instrument, midi) worth pre-rendering
        self.switch(region, first=1)

    # ---- region / key -----------------------------------------------------------

    def switch(self, region, first=0):
        name = style_for(region)
        r = rng.Rng(self.seed * 31 + len(region) * 7 + self.beats_written)
        self.region = region
        self.style_name = name
        self.style = STYLES[name]
        self.scale = SCALES[self.style['scale']]
        self.chords = CHORDS[self.style['scale']]
        self.chord = self.chords[0]
        self.root = into_range(HOME_KEY + self.style['key'], 52, 63)
        self.bar = 0
        self.beat = 0
        self.phrases = {}
        self.arp_i = 0
        self.tension = 0
        if not first:
            self.crash_pending = 1
        lo, hi = self.style['lead_range']
        self.deg_lo = self._degree_at_or_above(lo)
        self.deg_hi = self._degree_at_or_below(hi)
        self._plan_warm()

    def _degree_at_or_above(self, midi):
        d = -21
        while scale_note(self.root, self.scale, d) < midi:
            d += 1
        return d

    def _degree_at_or_below(self, midi):
        d = 35
        while scale_note(self.root, self.scale, d) > midi:
            d -= 1
        return d

    def _plan_warm(self):
        """Every note this style can ask for, so the cache misses happen in
        spare frame time rather than in the beat that needs them."""
        warm = []
        s = self.style
        # Roughly in the order the first bars will ask for them.
        if s['bass']:
            for ch in self.chords:
                warm.append((s['bass'], into_range(self.root + ch[0], BASS_RANGE[0], BASS_RANGE[1])))
        if s['pad']:
            for t in chord_tones(self.root, self.chords[0]):
                warm.append((s['pad'], into_range(t, PAD_RANGE[0], PAD_RANGE[1])))
        if s['arp']:
            for ch in self.chords:
                for t in chord_tones(self.root, ch) + (self.root + ch[0] + 12,):
                    warm.append((s['arp'], into_range(t, PAD_RANGE[0], PAD_RANGE[1] + 12)))
        if s['lead']:
            for d in range(self.deg_lo, self.deg_hi + 1):
                warm.append((s['lead'], scale_note(self.root, self.scale, d)))
        if s['pad']:
            for ch in self.chords:
                for t in chord_tones(self.root, ch):
                    warm.append((s['pad'], into_range(t, PAD_RANGE[0], PAD_RANGE[1])))
        if s['bass']:
            for ch in self.chords:
                for iv in (7, 12, 3, 4, 9, 10):
                    warm.append((s['bass'], into_range(self.root + ch[0] + iv, BASS_RANGE[0], BASS_RANGE[1])))
        seen = {}
        self.warm = []
        for w in warm:
            if w not in seen:
                seen[w] = 1
                self.warm.append(w)

    # ---- phrases ----------------------------------------------------------------

    def _phrase(self, letter, contour):
        """A two-bar lead phrase, cached per (period, letter)."""
        period = self.bar // 8
        key = (period, letter)
        p = self.phrases.get(key)
        if p is not None:
            return p
        r = rng.Rng(self.seed * 7919 + self.beats_written * 13 + period * 101 + ord(letter))
        spb = self.style['meter'] * STEPS
        total = spb * 2
        k = int(round(2 + self.style['density'] * 7 + self.intensity))
        if letter == 'B':
            k += 1
        onsets = []
        for bar in (0, 1):
            e = euclid(k, spb, r.pick(0, spb))
            for s in e:
                onsets.append(bar * spb + s)
        if 0 not in onsets:
            onsets.append(0)
        onsets.sort()
        span = self.deg_hi - self.deg_lo
        deg = self.deg_lo + span // 3 + r.pick(0, span // 3 + 1)
        if letter == 'B':
            deg += 2
        up = 3 + int(round(2 * contour))
        dn = 3 - int(round(2 * contour))
        if up < 1:
            up = 1
        if dn < 1:
            dn = 1
        notes = []
        i = 0
        while i < len(onsets):
            s = onsets[i]
            nxt = (i + 1 < len(onsets)) and onsets[i + 1] or total
            length = nxt - s
            if length > 4:
                length = 4
            if i > 0:
                move = r.weighted(((-2, dn), (-1, dn + 2), (0, 2), (1, up + 2), (2, up),
                                   (-4, 1), (4, 1)))
                deg += move
                if deg > self.deg_hi:
                    deg = self.deg_hi - (deg - self.deg_hi)
                if deg < self.deg_lo:
                    deg = self.deg_lo + (self.deg_lo - deg)
            notes.append((s, deg, length))
            i += 1
        self.phrases[key] = notes
        if len(self.phrases) > 8:
            for old in list(self.phrases.keys()):
                if old[0] < period:
                    del self.phrases[old]
        return notes

    # ---- the beat -----------------------------------------------------------------

    def next_beat(self, ctx):
        """-> a beat plan: {'bpm', 'crash', 'drum_key', 'drums': [(kind, step,
        gain)], 'notes': [(group, instrument, midi, step, gain)], 'chords':
        [(group, instrument, midis, steps, gain)]}. Music._render_block turns
        it into samples; the drum beat and each chord become one add."""
        region = ctx.get('region', self.region)
        if region != self.region:
            # A collision shrinks the lookahead, which can flip the "now"
            # region back for a beat; switch only when the farther look
            # agrees, or the same new region shows up twice running.
            if ctx.get('soon_region', region) == region or self.pending_region == region:
                self.switch(region)
            else:
                self.pending_region = region
                region = self.region
        else:
            self.pending_region = None
        s = self.style
        meter = s['meter']
        spb = meter * STEPS
        r = rng.Rng(self.seed * 104729 + self.beats_written)

        speed = ctx.get('speed', 0.6)
        curve = ctx.get('curve', 0.0)
        surface = ctx.get('surface', 'road')
        soon_motif = ctx.get('soon_motif', '')
        now_motif = ctx.get('motif', '')
        self.thin = ctx.get('soon_region', region) != region

        # Intensity from speed, with hysteresis so it doesn't flicker at a
        # threshold. Off the road the arrangement drops to drums and bass.
        target = 0
        if speed > 0.3:
            target = 1
        if speed > 0.6:
            target = 2
        if speed > 0.86:
            target = 3
        if target > self.intensity + 1:
            target = self.intensity + 1
        if target != self.intensity:
            if abs(speed - (0.3, 0.6, 0.86, 1.1)[min(target, self.intensity)]) > 0.04:
                self.intensity = target
        level = self.intensity
        if surface != 'road':
            level = 0

        # Corners: build up on the way in, crash on entry.
        corner_soon = soon_motif in CORNER_MOTIFS
        corner_now = now_motif in CORNER_MOTIFS
        if corner_now and not self.in_corner:
            self.crash_pending = 1
        self.in_corner = corner_now
        if corner_soon and not corner_now and self.intensity >= 1:
            self.tension += 1
        else:
            self.tension = 0
        tension = self.tension > 0 and self.tension <= meter * 2

        if self.beat == 0:
            self._next_chord(r)
            if self.hit_rest > 0:
                self.hit_rest -= 1

        # Tempo in 3-bpm steps: the drum beat and arp caches key on it.
        bpm = int(round(s['bpm'] * (0.92 + 0.16 * speed) / 3.0)) * 3
        step0 = self.beat * STEPS
        tones = chord_tones(self.root, self.chord)
        fill = (self.bar % 4 == 3) and (self.beat == meter - 1) and level >= 1

        # -- drums: one pre-mixed beat (cached by everything it depends on)
        crash = 0
        if self.crash_pending:
            crash = 1
            self.crash_pending = 0
        hits = []
        if tension:
            g0 = 0.3 + 0.6 * (self.tension / float(meter * 2))
            for st in range(STEPS):
                hits.append(('snare', st, (g0 + 0.15 * st / 3.0) * GAIN['drum']))
            hits.append(('kick', 0, GAIN['drum']))
            drum_key = ('roll', self.tension, bpm)
        else:
            kick, snare, hat = DRUMS[s['drums']][min(level, 2)]
            for st in range(STEPS):
                i = (step0 + st) % len(kick)
                if kick[i] == 'x':
                    hits.append(('kick', st, GAIN['drum']))
                if fill:
                    hits.append(('snare', st, (0.5 + 0.15 * st) * GAIN['drum']))
                elif snare[i] == 'x':
                    hits.append(('snare', st, 0.9 * GAIN['drum']))
                if hat[i] == 'x' and not self.thin:
                    g = (st % 2 == 0) and 0.5 or 0.3
                    hits.append(('hat', st, g * GAIN['drum']))
                elif hat[i] == 'o':
                    hits.append(('openhat', st, 0.5 * GAIN['drum']))
            drum_key = (s['drums'], min(level, 2), step0 % len(kick), fill, self.thin, bpm)

        notes = []          # (group, instrument, midi, step, gain): one add each
        chords = []         # (group, instrument, midis, steps, gain): pre-mixed, one add

        # -- bass
        if s['bass']:
            pat = BASS[s['bass_pat']]
            beat_pat = pat[self.beat % len(pat)]
            if tension:
                beat_pat = ((0, 0, 2), (2, 0, 2))
            for st, iv, length in beat_pat:
                if level == 0 and st > 0:
                    continue
                if iv == 'third':
                    iv = (self.chord[1] == 'maj') and 4 or 3
                elif iv == 'sixth':
                    iv = (self.chord[1] == 'maj') and 9 or 10
                midi = into_range(self.root + self.chord[0] + iv, BASS_RANGE[0], BASS_RANGE[1])
                notes.append(('c', s['bass'], midi, st, GAIN['bass']))

        # -- pad: the chord as one pre-mixed sample
        if s['pad'] and level >= 1 and not tension and not self.thin:
            mode = s['pad_mode']
            steps = ()
            if mode == 'hold' and self.beat == 0:
                steps = (0,)
            elif mode == 'stab' and (self.beat % 2 == 1):
                steps = (2,)
            elif mode == 'waltz' and self.beat > 0:
                steps = (0,)
            if steps:
                midis = []
                for t in tones:
                    midis.append(into_range(t, PAD_RANGE[0], PAD_RANGE[1]))
                chords.append(('r', s['pad'], tuple(midis), steps, GAIN['pad']))

        # -- arp: chord tones cycling every sixteenth; direction follows the bend
        if s['arp'] and level >= 1:
            cyc = list(tones) + [self.root + self.chord[0] + 12]
            midis = []
            for st in range(STEPS):
                if curve < -0.5:
                    self.arp_i -= 1
                else:
                    self.arp_i += 1
                midis.append(into_range(cyc[self.arp_i % 4], PAD_RANGE[0], PAD_RANGE[1] + 12))
            chords.append(('r', s['arp'], tuple(midis), (0, 1, 2, 3), GAIN['arp']))

        # -- lead
        if s['lead'] and level >= 2 and not tension and self.hit_rest == 0:
            contour = curve / 3.0
            if contour > 1.0:
                contour = 1.0
            if contour < -1.0:
                contour = -1.0
            slope = ctx.get('slope', 0.0)
            letter = 'AABA'[(self.bar // 2) % 4]
            phrase = self._phrase(letter, contour)
            pstep = (self.bar % 2) * spb + step0
            for st, deg, length in phrase:
                if st < pstep or st >= pstep + STEPS:
                    continue
                if slope > 0.25:
                    deg += 2
                elif slope < -0.25:
                    deg -= 2
                midi = scale_note(self.root, self.scale, deg)
                if st % spb in (0, 2 * STEPS):
                    midi = nearest_tone(midi, tones)
                notes.append(('l', s['lead'], midi, st - pstep, GAIN['lead']))

        # advance
        self.beat += 1
        self.beats_written += 1
        if self.beat >= meter:
            self.beat = 0
            self.bar += 1
        return {'bpm': bpm, 'crash': crash, 'drum_key': drum_key, 'drums': hits,
                'notes': notes, 'chords': chords}

    def _next_chord(self, r):
        if self.bar % 4 == 0 and r.pick(0, 4):
            self.chord = self.chords[0]
            return
        items = []
        for ch in self.chords:
            if ch is not self.chord:
                items.append((ch, ch[2]))
        nxt = r.weighted(items)
        if nxt is not None:
            self.chord = nxt

    def hit(self):
        self.hit_rest = 2


# ---- feeding the mixer -----------------------------------------------------------

class Stream(object):
    """Keeps one SDL channel fed with rendered blocks, gaplessly.

    Channel.queue() holds exactly one Sound behind the playing one and the
    mixer swaps to it sample-accurately when the current one ends. A block
    is rendered as a generator so update() can advance it a step at a time
    inside a per-frame time budget. `channel` needs play/queue/get_queue/
    get_busy; tools/render_song.py passes an offline one.
    """

    def __init__(self, channel, render_fn):
        self.channel = channel
        self.render_fn = render_fn
        self.ready = []               # (sound, seconds) rendered, not yet handed over
        self.live = []
        self.job = None
        self.started = 0
        self.blocks = 0
        self.starves = 0
        self.starve_at = []
        self.worst_step = 0.0
        self.stopped = 0
        self.t_first = 0.0            # wall time of the first play
        self.handed = 0.0             # seconds of audio handed to the mixer since

    # The mixer runs ahead of the speaker: with the 4096-sample buffer,
    # PulseAudio pre-fills about half a second, so Channel.get_busy() goes
    # false and get_queue() empties that long before the audio is heard.
    # What has been handed over plays out at t_first + handed regardless,
    # so time is judged against that, not against the channel flags.

    def urgent(self, margin=0.35):
        """True when nothing is ready and the handed-over audio ends within `margin` s."""
        if self.ready or not self.started:
            return 0
        return time.time() > self.t_first + self.handed - margin

    def update(self, budget):
        if self.stopped:
            return
        self._feed()
        deadline = time.time() + budget
        want = AHEAD_BLOCKS + 1
        if not self.started:
            want = PRIME_BLOCKS
        while len(self.ready) < want:
            if self.job is None:
                self.job = self.render_fn()
                self.step = getattr(self.job, 'next', None) or self.job.__next__
            t0 = time.time()
            try:
                out = self.step()
            except StopIteration:
                self.job = None
                out = None
                continue
            dt = time.time() - t0
            if dt > self.worst_step:
                self.worst_step = dt
            if out is not None:
                self.ready.append(out)
                self.blocks += 1
                self.job = None
            if time.time() >= deadline:
                break
        self._feed()

    def _feed(self):
        ch = self.channel
        if not self.started:
            if self.ready:
                self.t_first = time.time()
                self._play(self.ready.pop(0))
                self.started = 1
            return
        if not ch.get_busy():
            # The mixer has consumed everything it was given. That is the
            # pre-buffer running ahead unless the audio itself is about to
            # run out, which is a real starve: a block was not rendered in
            # time. Either way the next block goes in now.
            if time.time() > self.t_first + self.handed - 0.1:
                self.starves += 1
                self.starve_at.append((self.blocks, len(self.ready), round(time.time() - self.t_first, 2)))
            if self.ready:
                self._play(self.ready.pop(0))
        elif ch.get_queue() is None and self.ready:
            snd, secs = self.ready.pop(0)
            ch.queue(snd)
            self.handed += secs
            self._keep(snd)

    def _play(self, item):
        snd, secs = item
        self.channel.play(snd)
        self.handed += secs
        self._keep(snd)

    def _keep(self, snd):
        # SDL does not own the Sound's memory; Python does. Hold the last few
        # so a block is never freed while the mixer is still reading it.
        if snd is not None:
            self.live.append(snd)
        while len(self.live) > 4:
            self.live.pop(0)

    def stop(self, fade_ms=600):
        self.stopped = 1
        self.ready = []
        try:
            self.channel.fadeout(fade_ms)
        except AttributeError:
            pass


class Music(object):
    """The facade game.py talks to."""

    def __init__(self, seed, region, make_sound=None, channel=None, sfx_channels=None,
                 warm_budget=0.4):
        if make_sound is None:
            make_sound = synth.make_sound
        if channel is None:
            import pygame
            channel = pygame.mixer.Channel(0)
            sfx_channels = [pygame.mixer.Channel(i) for i in (1, 2, 3)]
        self.make_sound = make_sound
        self.timing = {}
        t = time.time()
        self.bank = synth.NoteBank()
        self.kit = synth.DrumKit()
        self.timing['drums'] = time.time() - t
        self.composer = Composer(seed, region)
        self.stream = Stream(channel, self._render_block)
        self.sfx_channels = sfx_channels or []
        self.premixed = {}            # drum beats, chords, arps: key -> mono bytes
        self.premix_order = []
        self.ctx = {'speed': 0.0, 'curve': 0.0, 'slope': 0.0, 'surface': 'road',
                    'region': region, 'soon_region': region, 'motif': '', 'soon_motif': ''}
        self.carry = None
        self.warmed = 0
        t = time.time()
        self.sfx = self._build_sfx()
        self.timing['sfx'] = time.time() - t
        # The first style's notes, up to warm_budget seconds of them; the rest
        # render in spare frame time.
        t = time.time()
        while self.composer.warm and time.time() - t < warm_budget:
            self._warm_one()
        self.timing['warm'] = time.time() - t
        # Three beats ready before the first frame (one playing, one queued,
        # one in hand), so the frame loop starts with a beat of slack while
        # the caches are still cold.
        t = time.time()
        self.stream.update(5.0)
        self.timing['prime'] = time.time() - t

    # ---- per frame ------------------------------------------------------------------

    def update(self, ctx, budget=BUDGET_S):
        self.ctx = ctx
        t0 = time.time()
        # Nothing rendered ahead: work harder this frame (burstier, same total).
        # Queued beat about to end as well: harder still, rather than a gap.
        if self.stream.urgent():
            budget = budget * 6.0
        elif not self.stream.ready:
            budget = budget * 2.5
        self.stream.update(budget)
        # Spare time goes to pre-rendering the current style's notes.
        c = self.composer
        while c.warm and time.time() - t0 < budget and len(self.stream.ready) > AHEAD_BLOCKS:
            self._warm_one()

    def _warm_one(self):
        name, midi = self.composer.warm.pop(0)
        if not self.bank.has(name, midi):
            self.bank.get(name, midi)
            self.warmed += 1

    def event(self, name):
        """One-shots: 'hit', 'curb', 'grass', 'finish'. Immediate, on their own channels."""
        if name == 'hit':
            self.composer.hit()
        if name == 'finish':
            self.stream.stop(400)
            if 'finish' not in self.sfx:
                self.sfx['finish'] = self._build_finish()
        snd = self.sfx.get(name)
        if snd is None or not self.sfx_channels:
            return
        idx = {'hit': 0, 'finish': 0, 'curb': 1, 'grass': 2}.get(name, 1)
        self.sfx_channels[idx].play(snd)

    def stop(self):
        self.stream.stop()

    def stats(self):
        return {'blocks': self.stream.blocks, 'starves': self.stream.starves,
                'starve_at': self.stream.starve_at,
                'renders': self.bank.renders, 'worst_step_ms': self.stream.worst_step * 1000.0,
                'premixed': len(self.premixed), 'cached_notes': len(self.bank.notes)}

    # ---- rendering ----------------------------------------------------------------------

    def _premix(self, key, build):
        data = self.premixed.get(key)
        if data is None:
            data = build()
            self.premixed[key] = data
            self.premix_order.append(key)
            if len(self.premix_order) > 48:
                del self.premixed[self.premix_order.pop(0)]
        return data

    def _render_block(self):
        plan = self.composer.next_beat(self.ctx)
        beat_frames = int(synth.SR * 60.0 / plan['bpm'])
        step_frames = beat_frames / float(STEPS)
        mix = synth.Mixdown(beat_frames, self.carry)
        yield None

        if plan['drums']:
            hits = plan['drums']

            def build_drums():
                items = []
                for kind, st, gain in hits:
                    items.append((int(st * step_frames), self.kit.get(kind, gain)))
                return synth.premix(items)
            mix.add('c', 0, self._premix(('drums',) + plan['drum_key'], build_drums))
            yield None
        if plan['crash']:
            mix.add('c', 0, self.kit.get('crash', 0.55 * GAIN['drum']))

        for group, name, midis, steps, gain in plan['chords']:
            key = ('chord', name, midis, steps, plan['bpm'], synth.quantise_gain(gain))
            if key not in self.premixed:
                # A miss on all three notes at once would be a 60 ms step on
                # the device; render them one per step first.
                for midi in midis:
                    if not self.bank.has(name, midi):
                        self.bank.get(name, midi)
                        yield None

            def build_chord(name=name, midis=midis, steps=steps, gain=gain):
                items = []
                i = 0
                while i < len(midis):
                    st = steps[min(i, len(steps) - 1)]
                    items.append((int(st * step_frames), self.bank.get(name, midis[i], gain)))
                    i += 1
                return synth.premix(items)
            mix.add(group, int(steps[0] * step_frames), self._premix(key, build_chord))
            yield None

        for group, name, midi, st, gain in plan['notes']:
            mix.add(group, int(st * step_frames), self.bank.get(name, midi, gain))
            yield None

        stereo = mix.stereo(MASTER)
        self.carry = mix.carry
        yield None
        yield (self.make_sound(stereo), beat_frames / float(synth.SR))

    def _build_sfx(self):
        out = {}
        sr = synth.SR
        # hit: a semitone cluster and a snare, over in a third of a second
        mix = synth.Mixdown(int(sr * 0.4))
        for midi in (41, 42, 47):
            mix.add('c', 0, self.bank.get('pulse12', midi, 0.7))
        mix.add('c', 0, self.kit.get('snare', 0.9))
        mix.add('c', int(sr * 0.08), self.kit.get('crash', 0.35))
        out['hit'] = self.make_sound(mix.stereo(0.6))
        # curb / grass: what the vibrator is doing, audibly
        mix = synth.Mixdown(int(sr * 0.05))
        mix.add('c', 0, self.kit.get('click', 0.6))
        out['curb'] = self.make_sound(mix.stereo(0.6))
        mix = synth.Mixdown(int(sr * 0.25))
        mix.add('c', 0, self.kit.get('rumble', 0.8))
        out['grass'] = self.make_sound(mix.stereo(0.7))
        return out

    def _build_finish(self):
        """A rising arpeggio into a held chord. Rendered when the finish line
        is crossed, not at startup: it is 300 ms of work the start doesn't need."""
        sr = synth.SR
        mix = synth.Mixdown(int(sr * 1.8))
        i = 0
        for midi in (60, 64, 67, 72, 76):
            mix.add('l', int(sr * 0.09 * i), self.bank.get('pulse25', midi, 0.6))
            i += 1
        for midi in (48, 55, 60, 64):
            mix.add('r', int(sr * 0.45), self.bank.get('organ', midi, 0.6))
        mix.add('c', int(sr * 0.45), self.kit.get('crash', 0.5))
        return self.make_sound(mix.stereo(0.8))


# ---- reading the road ------------------------------------------------------------------

def _chunk_at(win, seg, seg_len):
    """(region, motif, kind) of the chunk containing absolute segment `seg`."""
    log = win.chunk_log
    i = len(log) - 1
    while i >= 0:
        if log[i][0] <= seg:
            return log[i][1], log[i][3], log[i][4]
        i -= 1
    if log:
        return log[0][1], log[0][3], log[0][4]
    return win.region_at(seg * seg_len), '', ''


def road_context(win, player_z, speed, max_speed, surface, seg_len):
    """What the composer needs, read from the window ahead of the car.

    "now" is NOW_S seconds down the road, which is when the beat being
    written will actually be heard; "soon" is SOON_S seconds down, for
    build-ups. Both have a floor so a stopped car still looks at the road
    in front of it.
    """
    frac = speed / max_speed
    if frac > 1.0:
        frac = 1.0
    seg = int(player_z / seg_len)
    look_now = int(speed * NOW_S / seg_len)
    look_soon = int(speed * SOON_S / seg_len)
    if look_now < MIN_LOOK_SEGS:
        look_now = MIN_LOOK_SEGS
    if look_soon < MIN_LOOK_SEGS * 2:
        look_soon = MIN_LOOK_SEGS * 2
    limit = seg + win.ahead(player_z) - 1
    now_seg = min(seg + look_now, limit)
    soon_seg = min(seg + look_soon, limit)
    region, motif, kind = _chunk_at(win, now_seg, seg_len)
    soon_region, soon_motif, soon_kind = _chunk_at(win, soon_seg, seg_len)
    curve, y_now, _, _ = win.segment_at(now_seg * seg_len)
    _, y_far, _, _ = win.segment_at(min(now_seg + 30, limit) * seg_len)
    slope = (y_far - y_now) / 600.0
    if slope > 1.0:
        slope = 1.0
    if slope < -1.0:
        slope = -1.0
    return {'speed': frac, 'curve': curve, 'slope': slope, 'surface': surface,
            'region': region, 'soon_region': soon_region,
            'motif': motif, 'soon_motif': soon_motif, 'kind': kind, 'soon_kind': soon_kind}


# ---- audition: hear a style without driving ------------------------------------------

def audition_window(names, seconds, max_speed=6000.0):
    """A window whose chunk_log walks through `names` on straight road, so a
    style can be listened to on its own. Used by the demo below and by
    tools/render_song.py --regions."""
    import track
    import window
    seg = track.SEGMENT_LENGTH
    total = int(seconds * max_speed / seg) + 400
    per = total // len(names)
    segs = []
    y = 0.0
    heading = 0.0
    for name in names:
        y, heading = track.expand_stretch(segs, per, 0.0, 0.0, track.DEFAULT_WIDTH,
                                          track.DEFAULT_WIDTH, y, heading, name)
    trk = {'name': 'audition', 'theme': names[0], 'par': 0.0, 'width': track.DEFAULT_WIDTH,
           'roads': [], 'obstacles': [], 'traffic': [], 'seed': 1, 'segments': segs,
           'finish_segment': None, 'lap_length': 1e12}
    track._pad_runway(segs, track.DRAW_DISTANCE)
    win = window.Window.from_track(trk)
    win.finish = None
    win.chunk_log = []
    i = 0
    while i < len(names):
        win.chunk_log.append((i * per, names[i], i, 'straight', 'road'))
        i += 1
    return win


def drive_step(win, z, speed, t, dt, max_speed=6000.0):
    """A toy driver for demos: lifts for corners, floors it otherwise."""
    curve, _, _, _ = win.segment_at(z)
    target = max_speed * (1.0 - 0.09 * abs(curve))
    if t < 3.0:
        target = max_speed * 0.2
    if speed < target:
        speed = min(target, speed + 2400.0 * dt)
    else:
        speed = max(target, speed - 2600.0 * dt)
    return z + speed * dt, speed


def demo(argv):
    """python2.5 music.py [seconds] [seed] [style,style,...]

    Plays through the real mixer with no display: a journey by seed, or an
    audition of the named styles. Prints region changes and the stream stats
    that game.py also reports."""
    import sys
    import pygame
    import track
    import window
    seconds = len(argv) > 0 and float(argv[0]) or 30.0
    seed = len(argv) > 1 and int(argv[1]) or 4471
    names = len(argv) > 2 and argv[2].split(',') or None
    pygame.mixer.init(*MIXER_ARGS)
    if names:
        win = audition_window(names, seconds)
    else:
        win = window.journey(seed)
    t_init = time.time()
    m = Music(seed, win.region_at(0.0))
    parts = ' '.join(['%s=%.0f' % (k, v * 1000) for k, v in sorted(m.timing.items())])
    sys.stdout.write('music init %.0f ms (%s ms), mixer %s\n' % (
        (time.time() - t_init) * 1000, parts, pygame.mixer.get_init()))
    max_speed = 6000.0
    seg = track.SEGMENT_LENGTH
    t0 = time.time()
    last = t0
    z = 0.0
    speed = 0.0
    region = None
    frames = 0
    worst_update = 0.0
    while time.time() - t0 < seconds:
        now = time.time()
        dt = now - last
        last = now
        z, speed = drive_step(win, z, speed, now - t0, dt, max_speed)
        if win.gen is not None:
            win.feed(z, 4)
            win.trim(z)
        ctx = road_context(win, z, speed, max_speed, 'road', seg)
        tu = time.time()
        m.update(ctx)
        tu = time.time() - tu
        if tu > worst_update:
            worst_update = tu
        if ctx['region'] != region:
            region = ctx['region']
            sys.stdout.write('%5.1fs region %s\n' % (now - t0, region))
        frames += 1
        time.sleep(0.04)
    st = m.stats()
    sys.stdout.write('MUSIC blocks=%d starves=%d at=%s renders=%d premixed=%d worst_step_ms=%.1f worst_update_ms=%.1f frames=%d\n' % (
        st['blocks'], st['starves'], st['starve_at'], st['renders'], st['premixed'], st['worst_step_ms'],
        worst_update * 1000, frames))
    m.stop()
    time.sleep(0.8)
    pygame.mixer.quit()
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(demo(sys.argv[1:]))
