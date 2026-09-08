# synth.py - a soundchip made of `array`, `audioop` and the SDL mixer.
# Python 2.5 safe, and the same code runs on Python 3 with tools/fake_audioop.py
# standing in for the audioop module that 3.13 removed.
#
# Nothing here computes samples one at a time in Python at play time. Measured
# on the N900 (docs/SOUNDTRACK.md): a pure-Python sample loop costs ~18 us per
# sample, i.e. 40% of the CPU for one 22 kHz voice, while audioop's add/mul/
# ratecv and `array * n` run at C speed (a few ms per second of audio). So:
#
#   - a note is a single integer-period cycle looked up from a 1024-entry
#     wavetable (P Python operations, P <= 400), replicated with `array * n`,
#     tuned to the exact pitch with audioop.ratecv at a ratio near 1.0, and
#     shaped by a chunked audioop.mul envelope. ~8 ms for a 0.4 s note. Notes
#     are cached per (instrument, midi note) as mono int16 bytes.
#   - drums are rendered once at startup by the one pure-Python loop in this
#     file (about 30k samples, ~0.5 s on the device).
#   - a Mixdown is one beat of music: notes are audioop.add-ed into it at
#     sample offsets, in three pan groups, and folded to stereo at the end.
#     Note tails that run past the block are carried into the next one.
#
# pygame is imported only inside make_sound(), so this module also loads on a
# laptop with no pygame for tools/render_song.py.
import array
import audioop
import math
import struct

SR = 22050
TABLE = 1024
TABLE_MASK = TABLE - 1
TABLE_AMP = 24000             # int16 headroom for a single voice at gain 1.0

_EMPTY = ''.encode('latin-1')
_ZERO = struct.pack('<h', 0)


def _bytes(arr):
    """array -> bytes, on 2.5 (tostring) and 3.14 (tobytes)."""
    f = getattr(arr, 'tobytes', None)
    if f is None:
        f = arr.tostring
    return f()


def silence(n_frames):
    return _ZERO * n_frames


def frames(data):
    """Mono int16 byte string -> number of samples."""
    return len(data) // 2


# ---- wavetables --------------------------------------------------------------

def _table_fn(name):
    if name == 'saw':
        return lambda t: 2.0 * t - 1.0
    if name == 'square' or name == 'pulse25' or name == 'pulse12':
        duty = {'square': 0.5, 'pulse25': 0.25, 'pulse12': 0.125}[name]
        def pulse(t):
            if t < duty:
                return 1.0
            return -1.0
        return pulse
    if name == 'tri':
        def tri(t):
            if t < 0.5:
                return 4.0 * t - 1.0
            return 3.0 - 4.0 * t
        return tri
    if name == 'organ':
        # Three drawbars: fundamental, octave, twelfth. Reads as an organ
        # or a bell depending on the envelope it gets.
        return lambda t: (math.sin(2 * math.pi * t) + 0.5 * math.sin(4 * math.pi * t)
                          + 0.3 * math.sin(6 * math.pi * t)) / 1.8
    return lambda t: math.sin(2 * math.pi * t)


_TABLES = {}


def table(name):
    """1024-entry int16 wavetable for a wave name, built on first use."""
    t = _TABLES.get(name)
    if t is None:
        fn = _table_fn(name)
        t = array.array('h', [int(fn(i / float(TABLE)) * TABLE_AMP) for i in range(TABLE)])
        _TABLES[name] = t
    return t


def midi_hz(midi):
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def tone(wave, hz, n_frames):
    """`n_frames` samples of a wave at exactly `hz`, full table amplitude."""
    tbl = table(wave)
    period = int(round(SR / hz))
    if period < 2:
        period = 2
    cyc = array.array('h', [tbl[(i * TABLE) // period] for i in range(period)])
    reps = n_frames // period + 2
    raw = _bytes(cyc * reps)
    # The integer period plays at SR/period Hz; ratecv corrects that to hz.
    # The ratio is near 1.0, so input and output are the same size and the
    # cost is a few ms per second of audio, not the 50 ms a big table costs.
    inrate = int(round(hz * period * 64))
    outrate = SR * 64
    if inrate != outrate:
        raw, _ = audioop.ratecv(raw, 2, 1, inrate, outrate, None)
    raw = raw[:n_frames * 2]
    short = n_frames - frames(raw)
    if short > 0:
        raw = raw + silence(short)
    return raw


def envelope(data, attack, decay, sustain=0.0):
    """Attack/decay envelope by chunked gain steps.

    64-sample steps (3 ms) through the attack and the first 20 ms, 256-sample
    steps after that: the ear does not hear 11 ms gain steps on a decay, and
    it does hear them on an attack. `decay` is the exponential time constant
    in seconds; `sustain` is the floor the decay settles on (0 = to silence).
    """
    n = frames(data)
    out = []
    i = 0
    fine_until = int(SR * max(attack, 0.02))
    coarse_from = int(SR * 0.3)
    while i < n:
        if i < fine_until:
            step = 64
        elif i < coarse_from:
            step = 256
        else:
            step = 512
        t = i / float(SR)
        g = math.exp(-t / decay) * (1.0 - sustain) + sustain
        if attack > 0.0 and t < attack:
            g *= t / attack
        out.append(audioop.mul(data[i * 2:(i + step) * 2], 2, g))
        i += step
    return _EMPTY.join(out)


# ---- instruments -------------------------------------------------------------
#
# 'wave'   : table name
# 'attack' : seconds
# 'decay'  : exponential time constant, seconds
# 'sustain': floor the decay settles on (0..1)
# 'len'    : rendered length, seconds; longer notes are cut with a short fade
# 'gain'   : level relative to TABLE_AMP
# 'detune' : cents; a second copy this far sharp is mixed in (chorus/pad)
INSTRUMENTS = {
    'tri':      {'wave': 'tri',     'attack': 0.004, 'decay': 0.35, 'sustain': 0.0, 'len': 0.45, 'gain': 0.9},
    'sinebass': {'wave': 'sine',    'attack': 0.006, 'decay': 0.40, 'sustain': 0.0, 'len': 0.50, 'gain': 1.0},
    'sawbass':  {'wave': 'saw',     'attack': 0.003, 'decay': 0.22, 'sustain': 0.0, 'len': 0.35, 'gain': 0.55},
    'sqbass':   {'wave': 'square',  'attack': 0.003, 'decay': 0.18, 'sustain': 0.0, 'len': 0.30, 'gain': 0.5},
    'pulse25':  {'wave': 'pulse25', 'attack': 0.004, 'decay': 0.30, 'sustain': 0.0, 'len': 0.50, 'gain': 0.5},
    'pulse12':  {'wave': 'pulse12', 'attack': 0.003, 'decay': 0.12, 'sustain': 0.0, 'len': 0.20, 'gain': 0.55},
    'square':   {'wave': 'square',  'attack': 0.004, 'decay': 0.28, 'sustain': 0.0, 'len': 0.45, 'gain': 0.45},
    'sawlead':  {'wave': 'saw',     'attack': 0.010, 'decay': 0.35, 'sustain': 0.0, 'len': 0.50, 'gain': 0.40, 'detune': 7.0},
    'sine':     {'wave': 'sine',    'attack': 0.015, 'decay': 0.45, 'sustain': 0.0, 'len': 0.60, 'gain': 0.9},
    'organ':    {'wave': 'organ',   'attack': 0.040, 'decay': 0.75, 'sustain': 0.0, 'len': 0.90, 'gain': 0.5, 'detune': 5.0},
    'brass':    {'wave': 'saw',     'attack': 0.030, 'decay': 0.30, 'sustain': 0.0, 'len': 0.40, 'gain': 0.35, 'detune': 9.0},
}


def render_note(name, midi):
    """Mono int16 bytes for one note of an instrument."""
    ins = INSTRUMENTS[name]
    n = int(SR * ins['len'])
    hz = midi_hz(midi)
    raw = tone(ins['wave'], hz, n)
    detune = ins.get('detune', 0.0)
    if detune:
        second = tone(ins['wave'], hz * (2.0 ** (detune / 1200.0)), n)
        raw = audioop.add(audioop.mul(raw, 2, 0.5), audioop.mul(second, 2, 0.5), 2)
    raw = envelope(raw, ins['attack'], ins['decay'], ins['sustain'])
    g = ins['gain']
    if g != 1.0:
        raw = audioop.mul(raw, 2, g)
    return raw


def quantise_gain(gain):
    """Gains are cached in 1/16 steps so a note at a given level is scaled once."""
    return int(round(gain * 16.0)) / 16.0


class NoteBank(object):
    """Cache of rendered notes, per (instrument, midi, gain), capped so the
    device's tight RAM stays tight. ~20 KB a note; 200 notes is 4 MB."""

    def __init__(self, limit=200):
        self.notes = {}
        self.order = []
        self.limit = limit
        self.renders = 0

    def get(self, name, midi, gain=1.0):
        gain = quantise_gain(gain)
        key = (name, midi, gain)
        data = self.notes.get(key)
        if data is None:
            base = self.notes.get((name, midi, 1.0))
            if base is None:
                base = render_note(name, midi)
                self.renders += 1
                self._put((name, midi, 1.0), base)
            if gain == 1.0:
                data = base
            else:
                data = audioop.mul(base, 2, gain)
                self._put(key, data)
        return data

    def _put(self, key, data):
        self.notes[key] = data
        self.order.append(key)
        if len(self.order) > self.limit:
            old = self.order.pop(0)
            if old in self.notes:
                del self.notes[old]

    def has(self, name, midi):
        return (name, midi, 1.0) in self.notes


# ---- drums --------------------------------------------------------------------
#
# Noise is one deterministic LCG buffer made once (the only per-sample Python
# loop left, ~12k iterations); every drum is that buffer sliced, filtered
# and shaped with audioop. The kick is the exception: a pitch sweep, done as
# a short Python loop because it is 0.2 s long and rendered once.

NOISE_FRAMES = 8000
_NOISE = None


def noise(n_frames):
    global _NOISE
    if _NOISE is None:
        out = array.array('h')
        s = 24907
        for i in range(NOISE_FRAMES):
            # A 16-bit LCG on purpose: Python 2.5 on the N900 has 31-bit
            # ints, and a product that spills into longs runs ten times
            # slower. 25173 * 65535 stays inside.
            s = (s * 25173 + 13849) & 0xffff
            out.append(s - 32768)
        _NOISE = _bytes(out)
    return (_NOISE * (n_frames // NOISE_FRAMES + 1))[:n_frames * 2]


def highpass(data):
    """First difference, x[n] - x[n-1]: what turns noise into a cymbal."""
    return audioop.add(data[2:], audioop.mul(data[:-2], 2, -1.0), 2) + _ZERO


def lowpass(data, taps=8):
    """Running mean of `taps` samples: what turns noise into a rumble."""
    acc = audioop.mul(data, 2, 1.0 / taps)
    for k in range(1, taps):
        shifted = _ZERO * k + acc[:-k * 2]
        acc = audioop.add(acc, shifted, 2)
    return acc


def render_drum(kind):
    """Mono int16 bytes for one drum hit."""
    if kind == 'kick':
        n = int(SR * 0.18)
        out = array.array('h')
        ph = 0.0
        g = 21000.0
        sweep = 110.0
        decay = math.exp(-11.0 / SR)
        sweep_decay = math.exp(-28.0 / SR)
        for i in range(n):
            ph += (40.0 + sweep) / SR
            out.append(int(math.sin(2 * math.pi * ph) * g))
            g *= decay
            sweep *= sweep_decay
        return _bytes(out)
    if kind == 'snare':
        n = int(SR * 0.18)
        body = envelope(tone('square', 185.0, n), 0.0, 0.025)
        hiss = envelope(audioop.mul(noise(n), 2, 0.5), 0.0, 0.055)
        return audioop.add(audioop.mul(body, 2, 0.35), audioop.mul(hiss, 2, 0.9), 2)
    if kind == 'hat' or kind == 'openhat' or kind == 'crash':
        secs = {'hat': 0.05, 'openhat': 0.22, 'crash': 0.45}[kind]
        tau = {'hat': 0.022, 'openhat': 0.08, 'crash': 0.2}[kind]
        n = int(SR * secs)
        return envelope(audioop.mul(highpass(noise(n)), 2, 0.3), 0.0, tau)
    if kind == 'rumble':
        n = int(SR * 0.2)
        return envelope(audioop.mul(lowpass(noise(n), 10), 2, 0.9), 0.0, 0.11)
    if kind == 'click':
        n = int(SR * 0.025)
        return envelope(audioop.mul(noise(n), 2, 0.25), 0.0, 0.008)
    raise ValueError('unknown drum %r' % kind)


class DrumKit(object):
    KINDS = ('kick', 'snare', 'hat', 'openhat', 'crash', 'rumble', 'click')

    def __init__(self):
        self.samples = {}
        for k in self.KINDS:
            self.samples[(k, 1.0)] = render_drum(k)

    def get(self, kind, gain=1.0):
        gain = quantise_gain(gain)
        data = self.samples.get((kind, gain))
        if data is None:
            data = audioop.mul(self.samples[(kind, 1.0)], 2, gain)
            self.samples[(kind, gain)] = data
        return data


# ---- the block mixer -----------------------------------------------------------

# Pan groups: (left gain, right gain). Drums and bass sit in the middle; the
# lead leans left and the pad/arp lean right, the way a two-chip arcade board
# was wired.
GROUPS = {
    'c': (1.0, 1.0),
    'l': (1.0, 0.55),
    'r': (0.55, 1.0),
}


class Mixdown(object):
    """One block of music: mono buffers per pan group plus their carry-over.

    Notes are never cut short: an instrument's rendered length is its sound,
    and a decaying tail under the next note is what a real chip did too.
    Gains are applied by the caches (NoteBank / DrumKit), not here, so an add
    is one audioop.add and three slices.
    """

    def __init__(self, n_frames, carry=None):
        self.n = n_frames
        self.bufs = {}
        self.carry = {}
        self.touched = {}
        for g in GROUPS:
            prev = carry and carry.get(g) or _EMPTY
            head = prev[:n_frames * 2]
            self.touched[g] = len(head) > 0
            short = n_frames - frames(head)
            if short > 0:
                head = head + silence(short)
            self.bufs[g] = head
            self.carry[g] = prev[n_frames * 2:]

    def add(self, group, offset, data):
        """Mix `data` into the group at sample `offset`; spill into the carry."""
        self.touched[group] = 1
        n = frames(data)
        if offset < 0:
            data = data[-offset * 2:]
            n = frames(data)
            offset = 0
        room = self.n - offset
        if room <= 0:
            self._spill(group, offset - self.n, data)
            return
        if n > room:
            self._spill(group, 0, data[room * 2:])
            data = data[:room * 2]
            n = room
        buf = self.bufs[group]
        a = offset * 2
        b = a + n * 2
        self.bufs[group] = buf[:a] + audioop.add(buf[a:b], data, 2) + buf[b:]

    def _spill(self, group, offset, data):
        carry = self.carry[group]
        need = offset + frames(data)
        short = need - frames(carry)
        if short > 0:
            carry = carry + silence(short)
        a = offset * 2
        b = a + len(data)
        self.carry[group] = carry[:a] + audioop.add(carry[a:b], data, 2) + carry[b:]

    def stereo(self, master=1.0):
        """Fold the groups to one interleaved stereo int16 byte string.
        Groups nothing was mixed into this block are skipped."""
        out = None
        for g in GROUPS:
            if not self.touched[g]:
                continue
            lg, rg = GROUPS[g]
            st = audioop.tostereo(self.bufs[g], 2, lg * master, rg * master)
            if out is None:
                out = st
            else:
                out = audioop.add(out, st, 2)
        if out is None:
            out = silence(self.n * 2)
        return out


def premix(items, tail_frames=0):
    """Mono mix of (offset, data) pairs into one buffer: how a whole drum
    beat or a chord becomes a single add at play time."""
    n = tail_frames
    for offset, data in items:
        end = offset + frames(data)
        if end > n:
            n = end
    mix = Mixdown(n)
    for offset, data in items:
        mix.add('c', offset, data)
    return mix.bufs['c']


# ---- handing bytes to the SDL mixer ----------------------------------------------

def wav_bytes(stereo, rate=SR, channels=2):
    """A complete RIFF/WAVE file in memory around interleaved int16 PCM."""
    n = len(stereo)
    hdr = ('RIFF'.encode('latin-1') + struct.pack('<I', 36 + n) + 'WAVEfmt '.encode('latin-1')
           + struct.pack('<IHHIIHH', 16, 1, channels, rate, rate * 2 * channels, 2 * channels, 16)
           + 'data'.encode('latin-1') + struct.pack('<I', n))
    return hdr + stereo


def make_sound(stereo):
    """pygame.mixer.Sound from raw stereo int16 bytes.

    Always by way of a WAV in a file object. pygame 1.9.1's Sound(str) does
    build a valid sound from a byte string, but it also leaves a stale
    TypeError ("string without null bytes") in the interpreter that surfaces
    at the next unrelated C call - audioop.ratecv, in practice. Found on the
    device; see docs/SOUNDTRACK.md.
    """
    import pygame
    try:
        from cStringIO import StringIO as _IO
    except ImportError:
        from io import BytesIO as _IO
    return pygame.mixer.Sound(_IO(wav_bytes(stereo)))
