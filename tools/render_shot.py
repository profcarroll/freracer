"""Render frames of a track or a journey to PNG without a device, using tools/fake_pygame.

    python3 tools/render_shot.py tracks/001-autumn-hills.trk
    python3 tools/render_shot.py tracks/002-night-circuit.trk --at 6000 --offset 200
    python3 tools/render_shot.py tracks/001-autumn-hills.trk --frames 8 --out /tmp/shots
    python3 tools/render_shot.py tracks/001-autumn-hills.trk --min-band 3
    python3 tools/render_shot.py --journey 4471 --at 3200            # --at is a segment here
    python3 tools/render_shot.py --journey 4471 --frames 12 --out /tmp/shots

Look at the output before carrying a rendering change to the N900. Per-frame
`fills`/`polys` counts are printed too: they are a sanity check on how much the
renderer is actually asked to draw, not a performance measurement. For that,
run tools/racer_fps.py on the device.

For a journey, --at is an absolute segment index and --frames spreads frames
over the first --chunks chunks (default 40), so every region and boundary of a
seed can be looked at from the laptop.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                       # fake_pygame shadows pygame
sys.path.insert(1, os.path.join(HERE, '..'))

import fake_pygame
sys.modules['pygame'] = fake_pygame

import track                                   # noqa: E402
import window                                  # noqa: E402
import game                                    # noqa: E402


def build_scene(theme_names):
    bgs = {}
    backdrops = {}
    palettes = {}
    for name in theme_names:
        bgs[name] = game.build_theme_background(name)
        backdrops[name] = game.build_backdrop(name)
        palettes[name] = game.build_palette(name)
    return bgs, backdrops, palettes


def render(win, scene, z, offset, out):
    bgs, backdrops, palettes = scene
    screen = fake_pygame.display.set_mode((game.W, game.H))
    screen.calls = dict.fromkeys(screen.calls, 0)
    game.draw_road(screen, bgs, backdrops, win, palettes, z, offset)
    _, _, width, _ = win.segment_at(z)
    game.draw_car(screen, offset / (width * 2.0))
    fake_pygame.save_png(screen, out)
    print('%-40s z=%-8g offset=%-7g region=%-10s fills=%-4d polys=%d' % (
        out, z, offset, win.region_at(z), screen.calls['fill'], screen.calls['polygon']))


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    path = None
    seed = None
    chunks = 40
    at = None
    offset = 0.0
    frames = 1
    out_dir = '.'
    i = 1
    while i < len(argv):
        if argv[i] == '--journey':
            seed = int(argv[i + 1])
        elif argv[i] == '--chunks':
            chunks = int(argv[i + 1])
        elif argv[i] == '--at':
            at = float(argv[i + 1])
        elif argv[i] == '--offset':
            offset = float(argv[i + 1])
        elif argv[i] == '--frames':
            frames = int(argv[i + 1])
        elif argv[i] == '--out':
            out_dir = argv[i + 1]
        elif argv[i] == '--min-band':
            # See game.MIN_BAND_HEIGHT: the renderer is bound by draw calls
            # per frame, and this is the direct control on how many bands earn
            # their own. Worth looking at what a candidate value costs before
            # measuring what it buys with tools/racer_fps.py on the device.
            game.MIN_BAND_HEIGHT = float(argv[i + 1])
        elif argv[i].startswith('--'):
            sys.stderr.write('unknown option: %s\n' % argv[i])
            return 2
        else:
            path = argv[i]
            i -= 1
        i += 2

    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    if seed is not None:
        win = window.journey(seed)
        # Generate the whole span up front; nothing is trimmed, so any
        # segment of the first `chunks` chunks can be rendered.
        while win.gen.k < chunks:
            win.feed((len(win.segments) - 1) * track.SEGMENT_LENGTH, 100000)
        total = len(win.segments) - track.DRAW_DISTANCE
        scene = build_scene(sorted(set([s['region'] for s in win.segments])))
        stem = 'journey-%d' % seed
        for k in range(frames):
            seg = at if at is not None else total * (k + 0.5) / frames
            render(win, scene, seg * track.SEGMENT_LENGTH, offset, os.path.join(
                out_dir, '%s-mb%g-%02d.png' % (stem, game.MIN_BAND_HEIGHT, k)))
        return 0

    if path is None:
        sys.stderr.write(__doc__)
        return 2
    trk = track.load(path)
    errors = track.validate(trk)
    if errors:
        for e in errors:
            sys.stdout.write(e + '\n')
        return 2
    win = window.Window.from_track(trk)
    scene = build_scene([trk.get('theme', game.DEFAULT_THEME)])
    stem = os.path.splitext(os.path.basename(path))[0]
    lap = trk['lap_length']
    for k in range(frames):
        z = at if at is not None else lap * (k + 0.5) / frames
        render(win, scene, z, offset, os.path.join(
            out_dir, '%s-mb%g-%02d.png' % (stem, game.MIN_BAND_HEIGHT, k)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
