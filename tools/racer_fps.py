# racer_fps.py -- frame-rate measurement for the pseudo-3D road renderer on the N900.
# Python 2.5 / pygame 1.9.1. Exercises exactly what game.py draws per frame (road,
# rumble strips, lane markers, obstacle/traffic sprites) with no sensor reads, so it
# isolates render cost the way marble_fps.py isolated marble-physics cost in fremarble.
#
#   python2.5 tools/racer_fps.py [seconds] [draw_distance] [min_band_height]
#
# Writes a per-second fps log next to itself and prints a one-line summary. Run this
# on the device first and use the worst-second fps to pick DRAW_DISTANCE in game.py
# and track.py before trusting the game to be playable.
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pygame
import track
import game

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
if len(sys.argv) > 2:
    track.DRAW_DISTANCE = int(sys.argv[2])
    game.DRAW_DISTANCE = int(sys.argv[2])
# The renderer is bound by pygame draw calls per frame, not by pixels (see
# game.draw_road), and MIN_BAND_HEIGHT is the direct control on how many bands
# earn their own calls - so it is worth sweeping here alongside DRAW_DISTANCE.
if len(sys.argv) > 3:
    game.MIN_BAND_HEIGHT = float(sys.argv[3])

LOG = os.path.join(os.path.dirname(__file__), 'racer_fps.csv')

# A representative synthetic track: straights, sweepers, hills, a hairpin, plus
# obstacles and traffic so sprite-drawing cost is included in the measurement.
trk = {
    'name': 'fps probe',
    'theme': 'autumn-hills',
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
trk['segments'] = track._build_segments(trk['roads'], trk['width'])
trk['finish_segment'] = len(trk['segments'])
trk['lap_length'] = trk['finish_segment'] * track.SEGMENT_LENGTH
track._pad_runway(trk['segments'], track.DRAW_DISTANCE)

pygame.init()
pygame.mouse.set_visible(False)
screen = pygame.display.set_mode((game.W, game.H), pygame.FULLSCREEN, 16)
bg = game.build_theme_background(trk['theme'])
backdrop = game.build_backdrop(trk['theme'])
palette = game.build_palette(trk['theme'])

player_z = 0.0
player_x = 200.0
speed = 4000.0

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
    if player_z >= trk['lap_length']:
        player_z = 0.0
    player_x = 200.0 * ((player_z / 4000.0) % 2.0 - 1.0)

    game.draw_road(screen, bg, backdrop, trk, palette, player_z, player_x)
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
print 'draw_distance=%d min_band_h=%.1f frames=%d elapsed=%.1fs avg_fps=%.1f worst_second_fps=%.1f log=%s' % (
    track.DRAW_DISTANCE, game.MIN_BAND_HEIGHT, frames, elapsed, frames / elapsed, worst, LOG)
