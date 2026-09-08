# racer_fps.py -- frame-rate measurement for the pseudo-3D road renderer on the N900.
# Python 2.5 / pygame 1.9.1. Exercises exactly what game.py draws per frame (road,
# rumble strips, lane markers, obstacle/traffic sprites) with no sensor reads, so it
# isolates render cost the way marble_fps.py isolated marble-physics cost in fremarble.
#
#   python2.5 tools/racer_fps.py [seconds] [draw_distance] [min_band_height]
#   python2.5 tools/racer_fps.py 60 --journey 4471
#
# Writes a per-second fps log next to itself and prints a one-line summary. Run this
# on the device first and use the worst-second fps to pick DRAW_DISTANCE in game.py
# and track.py before trusting the game to be playable.
#
# --journey drives a generated road instead of the synthetic lap, feeding and
# trimming the window each frame exactly as game.py does, so the number it
# prints includes the cost of generating road on this CPU. It also counts
# starves (window.feed's return), which must be zero.
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pygame
import track
import window
import game

args = sys.argv[1:]
seed = None
if '--journey' in args:
    j = args.index('--journey')
    seed = 1
    if j + 1 < len(args):
        seed = int(args[j + 1])
        del args[j:j + 2]
    else:
        del args[j]

SECONDS = float(args[0]) if len(args) > 0 else 15.0
if len(args) > 1:
    track.DRAW_DISTANCE = int(args[1])
    game.DRAW_DISTANCE = int(args[1])
    window.DRAW_DISTANCE = int(args[1])
# The renderer is bound by pygame draw calls per frame, not by pixels (see
# game.draw_road), and MIN_BAND_HEIGHT is the direct control on how many bands
# earn their own calls - so it is worth sweeping here alongside DRAW_DISTANCE.
if len(args) > 2:
    game.MIN_BAND_HEIGHT = float(args[2])

LOG = os.path.join(os.path.dirname(__file__), 'racer_fps.csv')

if seed is None:
    # A representative synthetic track: straights, sweepers, hills, a hairpin, plus
    # obstacles and traffic so sprite-drawing cost is included in the measurement.
    trk = {
        'name': 'fps probe',
        'theme': 'autumn-hills',
        'seed': 1,
        'par': 60.0,
        'width': track.DEFAULT_WIDTH,
        'roads': [
            (60, 0.0, 0.0), (80, 3.0, 0.0), (40, 0.0, 400.0),
            (80, -5.0, -300.0), (60, 0.0, 0.0), (30, 6.0, 200.0),
            (60, 0.0, -200.0),
        ],
        'obstacles': [(70, -0.4, 'cone'), (150, 0.5, 'rock'), (300, 0.2, 'barrier')],
        'traffic': [(20, -0.5, 260.0, 'sedan'), (120, 0.5, 220.0, 'truck')],
        'finish_segment': None,
    }
    trk['segments'] = track._build_segments(trk['roads'], trk['width'], trk['theme'])
    trk['finish_segment'] = len(trk['segments'])
    trk['lap_length'] = trk['finish_segment'] * track.SEGMENT_LENGTH
    track._pad_runway(trk['segments'], track.DRAW_DISTANCE)
    win = window.Window.from_track(trk)
    themes = ['autumn-hills']
    label = 'probe'
else:
    win = window.journey(seed)
    themes = sorted(game.regions.REGIONS.keys())
    label = 'journey %d' % seed

pygame.init()
pygame.mouse.set_visible(False)
screen = pygame.display.set_mode((game.W, game.H), pygame.FULLSCREEN, 16)
bgs = {}
backdrops = {}
palettes = {}
for name in themes:
    bgs[name] = game.build_theme_background(name)
    backdrops[name] = game.build_backdrop(name)
    palettes[name] = game.build_palette(name)

player_z = 0.0
player_x = 200.0
speed = 4000.0
starves = 0

log = open(LOG, 'w')
log.write('t,fps,draw_distance\n')

t0 = time.time()
last_second = t0
sec_frames = 0
frames = 0
worst = 9999.0
running = True

while running and time.time() - t0 < SECONDS:
    for e in pygame.event.get():
        if e.type == pygame.QUIT or e.type == pygame.KEYDOWN or e.type == pygame.MOUSEBUTTONDOWN:
            running = False

    player_z += speed * 0.033
    if win.finish is not None and player_z >= win.lap_length:
        player_z = 0.0
    player_x = 200.0 * ((player_z / 4000.0) % 2.0 - 1.0)

    starves += win.feed(player_z)
    win.trim(player_z)
    game.draw_road(screen, bgs, backdrops, win, palettes, player_z, player_x)
    pygame.display.flip()

    frames += 1
    sec_frames += 1
    now = time.time()
    if now - last_second >= 1.0:
        fps = sec_frames / (now - last_second)
        if fps < worst:
            worst = fps
        log.write('%.1f,%.1f,%d\n' % (now - t0, fps, track.DRAW_DISTANCE))
        sec_frames = 0
        last_second = now

elapsed = time.time() - t0
log.close()
pygame.quit()
print '%s draw_distance=%d min_band_h=%.1f frames=%d elapsed=%.1fs avg_fps=%.1f worst_second_fps=%.1f starves=%d segments=%d log=%s' % (
    label, track.DRAW_DISTANCE, game.MIN_BAND_HEIGHT, frames, elapsed, frames / elapsed, worst,
    starves, int(player_z / track.SEGMENT_LENGTH), LOG)
