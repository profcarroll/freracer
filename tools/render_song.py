#!/usr/bin/env python3
# render_song.py - hear the soundtrack without the device.
#
# Drives music.py through a simulated journey (the real generator, the real
# window, a toy driver) and writes what the mixer would have played as a WAV,
# the way render_shot.py writes what the renderer would have drawn as a PNG.
#
#   python3 tools/render_song.py --seed 4471 --seconds 180 --out /tmp/seed4471.wav
#   python3 tools/render_song.py --track tracks/001-autumn-hills.trk --out /tmp/autumn.wav
#   python3 tools/render_song.py --regions farmland,mountains,coast --seconds 90
#
# --regions plays each named style for an equal share of the time on a
# synthetic road, which is the quick way to audition a style. Prints a
# timeline of region changes, corners and intensity steps.
import argparse
import os
import sys
import wave

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import audioop  # noqa: F401  (Python <= 3.12)
except ImportError:
    import fake_audioop
    sys.modules['audioop'] = fake_audioop

import music      # noqa: E402
import synth      # noqa: E402
import track      # noqa: E402
import window     # noqa: E402

FPS = 22.0                    # the device's frame rate: update() is called this often
MAX_SPEED = 6000.0
SEG = track.SEGMENT_LENGTH


class OfflineChannel(object):
    """A pygame Channel that writes to a byte list instead of a DAC."""

    def __init__(self):
        self.out = []
        self.cur = None
        self.pos = 0
        self.q = None
        self.gaps = 0

    def play(self, snd):
        self.cur = snd
        self.pos = 0
        self.q = None

    def queue(self, snd):
        self.q = snd

    def get_queue(self):
        return self.q

    def get_busy(self):
        return self.cur is not None

    def get_length(self):
        return 0.0

    def fadeout(self, ms):
        self.cur = None
        self.q = None

    def advance(self, n_frames):
        """Consume n_frames of playback (stereo int16: 4 bytes a frame)."""
        while n_frames > 0:
            if self.cur is None:
                self.out.append(synth.silence(n_frames * 2))
                self.gaps += 1
                return
            room = len(self.cur) // 4 - self.pos
            take = min(room, n_frames)
            self.out.append(self.cur[self.pos * 4:(self.pos + take) * 4])
            self.pos += take
            n_frames -= take
            if self.pos * 4 >= len(self.cur):
                self.cur = self.q
                self.q = None
                self.pos = 0


class SfxChannel(object):
    """One-shots are mixed straight onto the timeline at the current position."""

    def __init__(self, timeline):
        self.timeline = timeline

    def play(self, snd):
        self.timeline.append((self.timeline.pos, snd))


def identity_sound(stereo):
    return stereo


class Timeline(object):
    def __init__(self):
        self.pos = 0
        self.events = []

    def append(self, item):
        self.events.append(item)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', type=int, default=4471)
    ap.add_argument('--track')
    ap.add_argument('--regions', help='comma-separated style names to audition in turn')
    ap.add_argument('--seconds', type=float, default=120.0)
    ap.add_argument('--out', default='/tmp/freracer-song.wav')
    ap.add_argument('--hits', type=float, default=35.0, help='seconds between simulated collisions (0 = none)')
    args = ap.parse_args()

    if args.regions:
        names = args.regions.split(',')
        win = music.audition_window(names, args.seconds)
        seed = args.seed
    elif args.track:
        trk = track.load(args.track)
        win = window.Window.from_track(trk)
        seed = trk['seed']
    else:
        win = window.journey(args.seed)
        seed = args.seed

    region = win.region_at(0.0)
    chan = OfflineChannel()
    timeline = Timeline()
    sfx = [SfxChannel(timeline), SfxChannel(timeline), SfxChannel(timeline)]
    m = music.Music(seed, region, make_sound=identity_sound, channel=chan, sfx_channels=sfx)

    dt = 1.0 / FPS
    frames_per_tick = int(synth.SR / FPS)
    t = 0.0
    z = 0.0
    speed = 0.0
    surface = 'road'
    last = {}
    next_hit = args.hits or 1e9
    log = []

    def note(msg):
        log.append('%6.1fs  %s' % (t, msg))

    while t < args.seconds:
        # The toy driver lifts for corners and has bad luck every --hits seconds.
        z, speed = music.drive_step(win, z, speed, t, dt, MAX_SPEED)
        if t >= next_hit:
            m.event('hit')
            speed *= 0.35
            next_hit += args.hits
            note('hit')
        if win.gen is not None:
            win.feed(z, 4)
            win.trim(z)
        if win.finish is not None and z >= win.lap_length:
            note('finish')
            m.event('finish')
            break
        ctx = music.road_context(win, z, speed, MAX_SPEED, surface, SEG)
        m.update(ctx, budget=1.0)
        for key in ('region', 'soon_motif'):
            if ctx[key] != last.get(key):
                last[key] = ctx[key]
                note('%s -> %s' % (key, ctx[key]))
        lvl = m.composer.intensity
        if lvl != last.get('intensity'):
            last['intensity'] = lvl
            note('intensity %d (speed %.2f)' % (lvl, ctx['speed']))
        chan.advance(frames_per_tick)
        timeline.pos += frames_per_tick
        t += dt

    m.stop()
    pcm = bytearray(''.encode('latin-1').join(chan.out))
    # Lay the one-shots over the music.
    import numpy as np
    buf = np.frombuffer(bytes(pcm), dtype='<i2').astype(np.int32)
    for pos, snd in timeline.events:
        s = np.frombuffer(snd, dtype='<i2').astype(np.int32)
        a = pos * 2
        b = min(len(buf), a + len(s))
        if b > a:
            buf[a:b] += s[:b - a]
    buf = np.clip(buf, -32768, 32767).astype('<i2')
    w = wave.open(args.out, 'wb')
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(synth.SR)
    w.writeframes(buf.tobytes())
    w.close()

    for line in log:
        print(line)
    st = m.stats()
    peak = int(np.abs(buf.astype(np.int32)).max()) if len(buf) else 0
    print('wrote %s: %.1f s, blocks=%d starves=%d gaps=%d notes_rendered=%d peak=%d/32767' % (
        args.out, len(buf) / 2.0 / synth.SR, st['blocks'], st['starves'], chan.gaps, st['renders'], peak))


if __name__ == '__main__':
    main()
