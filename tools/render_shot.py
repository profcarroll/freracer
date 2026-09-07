"""Render frames of a track to PNG without a device, using tools/fake_pygame.

    python3 tools/render_shot.py tracks/001-autumn-hills.trk
    python3 tools/render_shot.py tracks/002-night-circuit.trk --at 6000 --offset 200
    python3 tools/render_shot.py tracks/001-autumn-hills.trk --frames 8 --out /tmp/shots
    python3 tools/render_shot.py tracks/001-autumn-hills.trk --min-band 3

Look at the output before carrying a rendering change to the N900. Per-frame
`fills`/`polys` counts are printed too: they are a sanity check on how much the
renderer is actually asked to draw, not a performance measurement. For that,
run tools/racer_fps.py on the device.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                       # fake_pygame shadows pygame
sys.path.insert(1, os.path.join(HERE, '..'))

import fake_pygame
sys.modules['pygame'] = fake_pygame

import track                                   # noqa: E402
import game                                    # noqa: E402


def render(trk, z, offset, out):
    theme = trk.get('theme', game.DEFAULT_THEME)
    screen = fake_pygame.display.set_mode((game.W, game.H))
    bg = game.build_theme_background(theme)
    backdrop = game.build_backdrop(theme)
    palette = game.build_palette(theme)
    screen.calls = dict.fromkeys(screen.calls, 0)
    game.draw_road(screen, bg, backdrop, trk, palette, z, offset)
    game.draw_car(screen, offset / (trk['width'] * 2.0))
    fake_pygame.save_png(screen, out)
    print('%-40s z=%-8g offset=%-7g fills=%-4d polys=%d' % (
        out, z, offset, screen.calls['fill'], screen.calls['polygon']))


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    path = argv[1]
    at = None
    offset = 0.0
    frames = 1
    out_dir = '.'
    i = 2
    while i < len(argv):
        if argv[i] == '--at':
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
        else:
            sys.stderr.write('unknown option: %s\n' % argv[i])
            return 2
        i += 2

    trk = track.load(path)
    errors = track.validate(trk)
    if errors:
        for e in errors:
            sys.stdout.write(e + '\n')
        return 2

    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    stem = os.path.splitext(os.path.basename(path))[0]
    lap = trk['lap_length']
    for k in range(frames):
        z = at if at is not None else lap * (k + 0.5) / frames
        render(trk, z, offset, os.path.join(
            out_dir, '%s-mb%g-%02d.png' % (stem, game.MIN_BAND_HEIGHT, k)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
