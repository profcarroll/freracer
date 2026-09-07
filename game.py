import math
import os
import re
import subprocess
import sys
import time
import pygame
import track
from telemetry import Telemetry

DEVNULL = open(os.devnull, 'wb')

ACCEL_PATH = '/sys/class/i2c-adapter/i2c-3/3-001d/coord'
VIBRATOR = '/sys/class/leds/twl4030:vibrator/brightness'

W = track.SCREEN_W
H = track.SCREEN_H
SEGMENT_LENGTH = track.SEGMENT_LENGTH
DRAW_DISTANCE = track.DRAW_DISTANCE
CAMERA_HEIGHT = track.CAMERA_HEIGHT
CAMERA_DEPTH = 1.0 / math.tan((track.FIELD_OF_VIEW / 2.0) * math.pi / 180.0)

# --- steering / calibration: raw_x (roll axis when held landscape) adjusted
# by the level reading at startup drives left/right motion. See main()'s
# calibration block for the on-device measurement that picked this axis. ---
CALIBRATION_WINDOW = 0.5
TILT_DEAD_ZONE = 40.0
STEER_GAIN = 5.0          # world units/sec of lateral speed per milli-g at full speed
STEER_MIN_SPEED_FRAC = 0.15

# --- forward driving model: always-accelerating arcade feel, brake optional ---
MAX_SPEED = 6000.0        # world units / sec
ACCEL = 2400.0            # units/sec^2 toward MAX_SPEED
BRAKE_DECEL = 5200.0
OFFROAD_MAX_SPEED = MAX_SPEED * 0.45
CENTRIFUGAL = 0.0007      # curve pulls the car outward, proportional to speed
CAR_HALF_WIDTH = 120.0
OBSTACLE_HALF_WIDTH = 110.0
HIT_SPEED_SCALE = 0.35    # speed multiplier on obstacle/traffic collision

RUMBLE_ZONE = 1.12        # fraction of half-width where the rumble strip starts
GRASS_ZONE = 1.35         # fraction of half-width beyond which is grass (hard penalty)

THEMES = {
    'autumn-hills': {
        'sky': (250, 168, 96),
        'sky2': (255, 216, 158),
        'grass': (86, 104, 44),
        'grass2': (112, 132, 60),
    },
    'dusk-city': {
        'sky': (24, 20, 52),
        'sky2': (96, 64, 122),
        'grass': (24, 22, 42),
        'grass2': (44, 40, 74),
    },
    'coast': {
        'sky': (120, 190, 235),
        'sky2': (198, 228, 246),
        'grass': (32, 138, 84),
        'grass2': (52, 176, 110),
    },
}
DEFAULT_THEME = 'autumn-hills'

# 'sky2' is doing two jobs: it is the bottom of the sky gradient *and* the
# haze colour every distant thing fades into (see build_palette), so the road
# dissolves into the horizon instead of stopping dead at DRAW_DISTANCE in
# full-strength tarmac grey. Keep the two ends of each sky gradient close in
# hue or the fade will read as a colour cast rather than as distance.

# Road paint: dark neutral tarmac in a light/dark pair that alternates every
# three segments. The alternation is the surface's only motion cue - on a real
# road that cue is texture, which we cannot afford to draw per pixel.
ROAD_COLOR = (42, 42, 48)
ROAD_COLOR2 = (66, 66, 74)
RUMBLE_LIGHT = (200, 60, 60)
RUMBLE_DARK = (230, 230, 230)
LANE_COLOR = (230, 220, 60)
POLE_LIGHT = (220, 40, 40)
POLE_DARK = (240, 240, 240)
POLE_INTERVAL = 5             # segments between roadside marker poles (500 world units)
POLE_OFFSET = 1.22            # fraction of half-width, just outside the rumble strip
POLE_HALF_WIDTH = 28.0
POLE_HEIGHT = 260.0

# Depth shading. Blending eight band colours per band per frame in Python on a
# 600 MHz CPU is not affordable, so build_palette() blends every colour at
# every distance once, at startup, and the frame loop just indexes the result.
FOG_STRENGTH = 0.72          # how far the furthest band goes toward the haze
FOG_CURVE = 2.0               # >1 keeps near ground crisp and fades late

# A band shorter than this is folded into the next one rather than drawn.
# Near the horizon dozens of segments land on the same scanline and giving
# each its own polygons buys nothing visible.
#
# This, not DRAW_DISTANCE, is the frame-rate dial. The renderer is bound by
# pygame draw calls per frame, not by pixels: measured on the device at
# DRAW_DISTANCE=120, min band height 1 -> 22.0 fps, 2 -> 24.5, 3 -> 26.5,
# 4 -> 27.6. DRAW_DISTANCE is a much blunter instrument by comparison
# (120 -> 26.4, 100 -> 27.7, 80 -> 29.5 at min band height 3) and it costs
# lookahead, which is what makes a corner readable at speed - 120 segments is
# two seconds of road at MAX_SPEED. Raising this instead costs only how
# finely the distant road is sliced, which the depth haze hides anyway.
#
# Do not raise it much past 3 without driving it: this quantises *which*
# segments get drawn, so as the camera moves the choice changes, and a coarse
# threshold can make the road stripes pop. That does not show up in a still.
MIN_BAND_HEIGHT = 3.0

# Nothing closer than this is projected. The near edge of the band the camera
# is standing in has dz ~ 0, and a point at dz -> 0 runs off along a fixed
# screen ray, so clamping dz only slides that vertex further out along a ray
# it is already on - the visible edges of the polygon are unchanged. What the
# clamp buys is bounded coordinates: pygame 1.9.1 draws polygons through
# 16-bit vertex maths, and an unclamped near vertex lands around x=100000.
# 100 rather than the smallest value that avoids visible artifacts (~40):
# the bound scales with the track's WIDTH and with how far off-centre the car
# has drifted, and 100 keeps a 1500-wide track at full drift inside 16 bits.
NEAR_PLANE = 100.0

BACKDROP_H = 96               # rows of distance scenery sitting on the horizon
BACKDROP_PAN = 2.5            # px of pan per world unit of centreline heading
HORIZON_Y = H // 2            # where dz -> infinity projects, hills aside

OBSTACLE_COLORS = {
    'rock': (110, 105, 100),
    'cone': (230, 120, 30),
    'barrier': (220, 40, 40),
    'tree-stump': (110, 70, 40),
}
TRAFFIC_COLORS = {
    'sedan': (60, 90, 200),
    'truck': (200, 200, 60),
    'tractor': (60, 160, 60),
}
SPRITE_FALLBACK = (150, 150, 150)
SPRITE_COLORS = {}
SPRITE_COLORS.update(OBSTACLE_COLORS)
SPRITE_COLORS.update(TRAFFIC_COLORS)


class _Rng(object):
    """Tiny deterministic LCG.

    The backdrop is generated rather than shipped as art, and it has to come
    out identical on the device and off it, so this does not use `random`
    (whose stream is not guaranteed stable across Python versions, and the
    device is on 2.5.4).
    """

    def __init__(self, seed):
        self.s = seed

    def pick(self, lo, hi):
        self.s = (1103515245 * self.s + 12345) % 2147483648
        return lo + self.s % (hi - lo)


def _blend(color, target, t):
    return (int(color[0] + (target[0] - color[0]) * t),
            int(color[1] + (target[1] - color[1]) * t),
            int(color[2] + (target[2] - color[2]) * t))


def build_backdrop(theme_name):
    """Distance scenery that pans sideways with the road\'s heading.

    Everything else in the frame says "the road ahead is bent". This is the
    only thing that says "you are turning", which is most of what a racer\'s
    sense of motion is made of. It sits on the vanishing point because it is
    notionally infinitely far away, so local hills do not move it - the road
    bands simply paint over it when the ground rises above the horizon.

    The tile is twice screen width and is blitted twice, wrapping. The sky
    gradient for these rows is baked into it so the blit can be opaque: a
    colour-keyed blit of 800x96 every frame is real work on this CPU, and an
    opaque one is a memcpy per row.
    """
    theme = THEMES.get(theme_name, THEMES[DEFAULT_THEME])
    sky = theme['sky']
    sky2 = theme['sky2']
    w = W * 2
    surf = pygame.Surface((w, BACKDROP_H)).convert()

    fade = int(H * 0.55)
    top = HORIZON_Y - BACKDROP_H
    y = 0
    while y < BACKDROP_H:
        sy = top + y
        if sy >= fade:
            c = sky2
        else:
            t = sy / float(fade)
            c = (int(sky[0] + (sky2[0] - sky[0]) * t),
                 int(sky[1] + (sky2[1] - sky[1]) * t),
                 int(sky[2] + (sky2[2] - sky[2]) * t))
        pygame.draw.line(surf, c, (0, y), (w, y))
        y += 1

    rng = _Rng(len(theme_name) * 7919 + 17)
    if theme_name == 'dusk-city':
        rank = 1
        while rank >= 0:
            haze = 0.30 + rank * 0.34
            col = _blend((16, 14, 30), sky2, haze)
            lit = _blend((255, 214, 120), sky2, haze * 0.8)
            x = -rng.pick(0, 40)
            while x < w:
                tw = rng.pick(16, 54)
                th = rng.pick(18, BACKDROP_H - 8 - rank * 20)
                surf.fill(col, (x, BACKDROP_H - th, tw, th))
                if rank == 0 and tw > 22:
                    k = 0
                    while k < th // 14:
                        surf.fill(lit, (x + rng.pick(4, tw - 6),
                                        BACKDROP_H - th + 6 + k * 14, 3, 4))
                        k += 1
                x += tw + rng.pick(3, 14)
            rank -= 1
    else:
        # Two ridge lines from harmonics of the tile width, so the seam where
        # the tile wraps is continuous.
        two_pi = math.pi * 2.0
        rank = 1
        while rank >= 0:
            haze = 0.34 + rank * 0.30
            col = _blend(theme['grass'], sky2, haze)
            base = 0.62 - rank * 0.16
            amp = 0.30 - rank * 0.10
            pts = [(0, BACKDROP_H)]
            j = 0
            while j <= w:
                u = j / float(w)
                hgt = (0.45 * math.sin(two_pi * (3 + rank * 2) * u) +
                       0.32 * math.sin(two_pi * (7 + rank) * u + 1.1 + rank) +
                       0.23 * math.sin(two_pi * 13 * u + 2.3))
                pts.append((j, int(BACKDROP_H * (base - amp * hgt))))
                j += 8
            pts.append((w, BACKDROP_H))
            pygame.draw.polygon(surf, col, pts)
            rank -= 1
    return surf


def build_palette(theme_name):
    """Pre-blend every colour the road renderer uses, at every distance.

    Returns (bands, poles, sprites), each indexed by how many segments ahead
    of the camera a thing is:
      bands[i][parity] -> (ground, rumble, road, lane)
      poles[i][parity] -> marker post colour
      sprites[i][kind] -> obstacle/traffic colour ('' is the fallback)
    """
    theme = THEMES.get(theme_name, THEMES[DEFAULT_THEME])
    haze = theme['sky2']
    bands = []
    poles = []
    sprites = []
    i = 0
    while i < DRAW_DISTANCE:
        f = FOG_STRENGTH * (i / float(DRAW_DISTANCE)) ** FOG_CURVE
        bands.append((
            (_blend(theme['grass'], haze, f), _blend(RUMBLE_LIGHT, haze, f),
             _blend(ROAD_COLOR, haze, f), _blend(LANE_COLOR, haze, f)),
            (_blend(theme['grass2'], haze, f), _blend(RUMBLE_DARK, haze, f),
             _blend(ROAD_COLOR2, haze, f), _blend(LANE_COLOR, haze, f)),
        ))
        poles.append((_blend(POLE_LIGHT, haze, f), _blend(POLE_DARK, haze, f)))
        sp = {'': _blend(SPRITE_FALLBACK, haze, f)}
        for kind in SPRITE_COLORS:
            sp[kind] = _blend(SPRITE_COLORS[kind], haze, f)
        sprites.append(sp)
        i += 1
    return bands, poles, sprites


def sanitize_name(name):
    s = re.sub('[^a-z0-9]+', '-', name.lower()).strip('-')
    return s or 'track'


def default_telemetry_path(track_path, trk):
    base = trk.get('name', '')
    if not base:
        base = os.path.splitext(os.path.basename(track_path))[0]
    base = sanitize_name(base)
    d = 'telemetry'
    if not os.path.isdir(d):
        os.makedirs(d)
    return os.path.join(d, base + '-' + str(int(time.time())) + '.csv')


def read_tilt(path, last):
    try:
        f = open(path, 'r')
        try:
            s = f.read()
        finally:
            f.close()
        parts = s.split()
        return int(parts[0]), int(parts[1]), int(parts[2])
    except Exception:
        return last


def write_vibrator(value):
    try:
        f = open(VIBRATOR, 'w')
        try:
            f.write(value)
        finally:
            f.close()
    except Exception:
        pass


VIBRATOR_PATTERNS = {
    'curb': 'PatternTouchscreen',        # short, light tap (curb)
    'grass': 'PatternChatAndEmail',      # medium single buzz
    'hit': 'PatternIncomingMessage',     # strong, self-repeating ~1s (any collision)
    'finish': 'PatternChatAndEmail',
}


def start_buzz_helper():
    # /sys/class/leds/twl4030:vibrator/brightness (write_vibrator, above) is
    # root-only (0644, root:root); a game launched from the Hildon desktop
    # runs as the unprivileged 'user' account and silently can't write it -
    # haptics never actually fired. The permission-safe path is MCE's own
    # vibrator-pattern D-Bus API (verified callable as 'user'). A first
    # attempt called `dbus-send` via subprocess.Popen directly from here on
    # every event; that forks the whole pygame-loaded game process, which
    # measurably stalled the frame loop on real hardware (playtest: "freezes
    # with rumbles" - sustained rumble-strip contact kept re-triggering the
    # fork every 0.35s). Spawning one small, idle buzz_helper.py process here
    # - before pygame/track surfaces grow this process - means later forks
    # happen inside that small helper instead, which is cheap.
    here = os.path.dirname(os.path.abspath(__file__))
    helper_path = os.path.join(here, 'buzz_helper.py')
    try:
        return subprocess.Popen(('python2.5', helper_path),
                                 stdin=subprocess.PIPE,
                                 stdout=DEVNULL, stderr=DEVNULL)
    except Exception:
        return None


def buzz_pattern(helper, name):
    if not helper:
        return
    try:
        helper.stdin.write(name + '\n')
        helper.stdin.flush()
    except Exception:
        pass


def buzz_event(helper, event_name):
    pattern = VIBRATOR_PATTERNS.get(event_name)
    if pattern:
        buzz_pattern(helper, pattern)


def stop_buzz_helper(helper):
    if not helper:
        return
    try:
        helper.stdin.close()
    except Exception:
        pass



def project(lateral, world_y, world_z, cam_y, cam_z, road_width):
    """Project a point given as a *lateral offset from the camera's line*.

    Nothing in the renderer works in absolute world x any more; see
    draw_road's road_x accumulator for why.
    """
    dz = world_z - cam_z
    if dz < NEAR_PLANE:
        dz = NEAR_PLANE
    scale = CAMERA_DEPTH / dz
    screen_x = (W / 2.0) + scale * lateral * (W / 2.0)
    screen_y = (H / 2.0) - scale * (world_y - cam_y) * (H / 2.0)
    screen_w = scale * road_width * (W / 2.0)
    return screen_x, screen_y, screen_w, scale


def build_theme_background(theme_name):
    """Sky gradient over the whole surface - no ground slab.

    The ground used to be a flat rectangle filling the bottom half here, and
    because draw_road was discarding every road band (see its docstring),
    that rectangle was almost the entire picture: what looked like a badly
    coloured road surface was this. The ground is now drawn per band by
    draw_road, one full-width stripe at a time, so it scrolls. What is left
    for this surface to provide is sky, and distance haze wherever the road
    has not reached - which is why the gradient runs out to sky2 and then
    holds it, rather than stopping at a horizon line.
    """
    theme = THEMES.get(theme_name, THEMES[DEFAULT_THEME])
    sky = theme['sky']
    sky2 = theme['sky2']
    bg = pygame.Surface((W, H)).convert()
    bg.fill(sky2)
    fade = int(H * 0.55)
    i = 0
    while i < fade:
        t = i / float(fade)
        r = int(sky[0] + (sky2[0] - sky[0]) * t)
        g = int(sky[1] + (sky2[1] - sky[1]) * t)
        b = int(sky[2] + (sky2[2] - sky[2]) * t)
        pygame.draw.line(bg, (r, g, b), (0, i), (W, i))
        i += 1
    return bg


def traffic_world_z(base_z, speed, t, lap_length):
    z = base_z + speed * t
    if lap_length > 0.0:
        z = z % lap_length
    return z


def find_obstacle_hit(obstacles, player_z, player_x, trk, hit_flags):
    i = 0
    while i < len(obstacles):
        seg_i, offset, kind = obstacles[i]
        if not hit_flags[i]:
            obs_z = seg_i * SEGMENT_LENGTH + SEGMENT_LENGTH / 2.0
            if abs(player_z - obs_z) < SEGMENT_LENGTH:
                # Compared in centreline-relative space, the same space
                # player_x and the off-road test live in. The old version
                # added the segment's absolute centreline x to the obstacle
                # and compared that against a relative player_x, so once the
                # centreline drifted from the origin nothing could ever be
                # hit.
                _, _, width, _ = track.segment_at(trk, obs_z)
                obs_x = offset * width
                if abs(player_x - obs_x) < (CAR_HALF_WIDTH + OBSTACLE_HALF_WIDTH):
                    hit_flags[i] = 1
                    return i, kind
        i += 1
    return -1, None


def find_traffic_hit(traffic, player_z, player_x, t, trk, cooldowns):
    i = 0
    while i < len(traffic):
        seg_i, offset, speed, kind = traffic[i]
        base_z = seg_i * SEGMENT_LENGTH
        car_z = traffic_world_z(base_z, speed, t, trk['lap_length'])
        if cooldowns[i] <= 0.0 and abs(player_z - car_z) < SEGMENT_LENGTH * 0.8:
            # Centreline-relative, as in find_obstacle_hit above.
            _, _, width, _ = track.segment_at(trk, car_z)
            car_x = offset * width
            if abs(player_x - car_x) < (CAR_HALF_WIDTH + OBSTACLE_HALF_WIDTH):
                cooldowns[i] = 2.0
                return i, kind
        i += 1
    return -1, None


def draw_road(screen, bg, backdrop, trk, palette, player_z, player_x):
    """Scanline road, walked near-to-far with a painter\'s clip.

    The walk direction is the whole trick, and getting it backwards is what
    made this renderer draw nothing. Near-to-far, each band is drawn from
    where the previous band stopped (ny) up to its own far edge (fy), so
    bands tile the screen without overlapping, and a band hidden behind a
    crest simply never clears the test. The previous version walked
    far-to-near while keeping this near-to-far clip, comparing a band\'s far
    edge against the previous band\'s near edge - but those are the same
    point, projected from the same segment at the same z, so the comparison
    was true by float equality and every band nearer than the first was
    thrown away. Exactly one 0.1px-tall band was drawn per frame.

    Walking in order pays for itself twice: adjacent segments share an
    endpoint, so each band reuses the previous band\'s far projection as its
    own near projection. One projection per segment instead of two.
    """
    band_pal = palette[0]
    pole_pal = palette[1]
    segments = trk['segments']
    n = len(segments)

    base_index = int(player_z / SEGMENT_LENGTH)
    if base_index >= n - 1:
        base_index = n - 2
    if base_index < 0:
        base_index = 0

    # player_x is an offset from the centreline, not a world coordinate - the
    # physics, the off-road test and draw_car all read it that way. The
    # centreline itself wanders a long way from the origin (track.py
    # integrates it from curve, so 001-autumn-hills reaches x=22320 by its
    # last segment), so the camera has to be placed relative to it. Setting
    # cam_x = player_x, as this did, pointed the camera at world x=+-3000 on
    # a track whose road was kilometres away: past the first straight, the
    # road was simply not in frame. Placing the camera on the centreline is
    # also what makes a bend read as a bend - the road ahead diverges from
    # the camera's fixed heading and sweeps across the screen.
    _, player_y, _, _ = track.segment_at(trk, player_z)
    cam_y = player_y + CAMERA_HEIGHT
    cam_z = player_z

    # project() is inlined below: it would run DRAW_DISTANCE times a frame and
    # the call overhead alone is measurable on a 600 MHz CPU.
    half_w = W / 2.0
    half_h = H / 2.0

    # Lateral offset of the centreline ahead of the camera, re-accumulated
    # from curve every frame starting at zero. track.py bakes an absolute
    # centreline x into each segment by integrating curve twice from the start
    # line; that is fine as data but cannot be projected against, because both
    # the offset and the *heading* it implies grow without bound - by segment
    # 330 of 001-autumn-hills the centreline is 22320 units from the origin
    # and pointing tens of degrees off +z. A camera looking down +z sees no
    # road. Restarting the accumulator at the camera is the standard
    # pseudo-3D treatment and amounts to aiming the camera down the road's
    # own tangent, so a bend sweeps across the screen instead of off it.
    road_x = 0.0
    road_dx = 0.0
    curve_off = []

    a = segments[base_index]
    dz = base_index * SEGMENT_LENGTH - cam_z
    if dz < NEAR_PLANE:
        dz = NEAR_PLANE
    s = CAMERA_DEPTH / dz
    nx = half_w + s * (-player_x) * half_w
    ny = half_h - s * (a['y'] - cam_y) * half_h
    nw = s * a['width'] * half_w

    poles = []
    i = 0
    while i < DRAW_DISTANCE:
        idx = base_index + i
        if idx >= n - 1:
            break
        b = segments[idx + 1]
        road_dx += segments[idx]['curve']
        road_x += road_dx
        curve_off.append(road_x)
        dz = (idx + 1) * SEGMENT_LENGTH - cam_z
        if dz < NEAR_PLANE:
            dz = NEAR_PLANE
        s = CAMERA_DEPTH / dz
        fx = half_w + s * (road_x - player_x) * half_w
        fy = half_h - s * (b['y'] - cam_y) * half_h
        fw = s * b['width'] * half_w

        # Marker posts are emitted before the band test, not inside it.
        # Whether a segment earns its own road band is a rasterisation
        # question - MIN_BAND_HEIGHT, tuned for frame rate - and tying the
        # roadside furniture to it meant raising that threshold silently
        # thinned the posts out with distance, losing the strongest cue for
        # how fast the road is going past.
        if idx % POLE_INTERVAL == 0:
            # Derived from the projection already in hand rather than
            # re-projecting the post's base and top: same scale factor, so
            # the post's screen height is just its world height times s.
            ph = s * POLE_HEIGHT * half_h
            if ph >= 2.0:
                pb = fw * (POLE_HALF_WIDTH / b['width'])
                if pb < 1.0:
                    pb = 1.0
                pc = pole_pal[i][(idx // POLE_INTERVAL) % 2]
                po = fw * POLE_OFFSET
                ptop = int(fy - ph)
                pwide = int(pb * 2.0)
                phigh = int(ph)
                poles.append((pc, int(fx - po - pb), ptop, pwide, phigh))
                poles.append((pc, int(fx + po - pb), ptop, pwide, phigh))

        # Behind a crest, or too short to earn its own polygons. Either way
        # leave the near edge where it is, so this segment is folded into
        # whichever band next clears the test and no gap opens up.
        if fy >= ny - MIN_BAND_HEIGHT:
            i += 1
            continue

        pal = band_pal[i][(idx // 3) % 2]

        # One full-width ground stripe per band. This is the periphery motion
        # cue: everything outside a narrow shoulder used to be a single static
        # colour, so nothing but the road itself could read as moving.
        #
        # The height is deliberately int(ny) - top, with no +1. Bands are
        # drawn near to far and band k's near edge is bit-identical to band
        # k-1's far edge, so a +1 made every band repaint the top row of the
        # band in front of it - a row the nearer band had already, correctly,
        # filled with road. The result was a full-width grass line punched
        # through the road at every band boundary, which in the middle
        # distance shredded the surface into alternating road and grass. It
        # read as "the road is the wrong colour". Without the +1 the stripes
        # tile exactly: [int(fy), int(ny)-1] then [int(ny), ...].
        #
        # One wide fill, not two narrow ones flanking the road. Filling the
        # pixels the road is about to cover is pure waste, but this device
        # charges by the draw call, not by the pixel: splitting this fill and
        # the rumble below into left/right halves saved ~440k pixels a frame
        # and cost 98 extra calls, and measured 22.0 -> 18.5 fps at
        # DRAW_DISTANCE=120. Fewer, bigger primitives win here.
        top = int(fy)
        height = int(ny) - top
        if height > 0:
            screen.fill(pal[0], (0, top, W, height))

        rn = nw * RUMBLE_ZONE
        rf = fw * RUMBLE_ZONE
        pygame.draw.polygon(screen, pal[1], (
            (nx - rn, ny), (nx + rn, ny), (fx + rf, fy), (fx - rf, fy)))
        pygame.draw.polygon(screen, pal[2], (
            (nx - nw, ny), (nx + nw, ny), (fx + fw, fy), (fx - fw, fy)))

        if idx % 6 < 3 and nw > 10.0:
            ln = nw * 0.035
            lf = fw * 0.035
            pygame.draw.polygon(screen, pal[3], (
                (nx - ln, ny), (nx + ln, ny), (fx + lf, fy), (fx - lf, fy)))

        nx = fx
        ny = fy
        nw = fw
        i += 1

    # Sky and scenery go in last, clipped to the rows the road did not reach.
    # The bands tile from the topmost far edge down to the bottom of the
    # screen and each one paints its own rows opaquely, so a full-screen
    # background blit before the walk was drawing ~190k pixels a frame that
    # were then painted over - about a fifth of the frame\'s whole fill budget
    # on a device with no blitter. Measured 22 fps at DRAW_DISTANCE=120 before
    # this; the road is fill-rate bound, not band-count bound (dropping the
    # draw distance from 120 to 50 was worth only 6 fps, because the bands
    # cover the same screen area either way).
    top_y = int(ny)
    if top_y > 0:
        if top_y > H:
            top_y = H
        screen.set_clip((0, 0, W, top_y))
        screen.blit(bg, (0, 0))
        # The camera looks down the centreline\'s tangent (see road_x above),
        # so the scenery pans by that tangent\'s heading. track.py\'s baked
        # centreline x is useless to project against, but its first difference
        # *is* that heading - the one thing it is good for.
        bw = backdrop.get_width()
        pan = int(-(segments[base_index + 1]['x'] - segments[base_index]['x'])
                  * BACKDROP_PAN) % bw
        btop = HORIZON_Y - BACKDROP_H
        screen.blit(backdrop, (pan - bw, btop))
        screen.blit(backdrop, (pan, btop))
        screen.set_clip(None)

    # Posts go in a second pass, far to near. A post stands *above* its own
    # band\'s far edge, which is territory the next band\'s ground stripe
    # paints over, so drawing them inline during a near-to-far walk would
    # bury every post except the last one. They come after the sky so a near
    # post may stand above the horizon.
    j = len(poles) - 1
    while j >= 0:
        p = poles[j]
        screen.fill(p[0], (p[1], p[2], p[3], p[4]))
        j -= 1

    return base_index, cam_y, cam_z, curve_off


def draw_sprite(screen, lateral, world_y, world_z, cam_y, cam_z, color, half_w):
    if world_z <= cam_z:
        return
    x, y, w, scale = project(lateral, world_y, world_z, cam_y, cam_z, half_w)
    if scale <= 0.0:
        return
    h = w * 1.4
    rect = pygame.Rect(int(x - w), int(y - h), int(w * 2), int(h))
    if rect.bottom < 0 or rect.top > H:
        return
    pygame.draw.rect(screen, color, rect)


def draw_car(screen, offset_frac):
    cx = W / 2 + int(offset_frac * 40)
    cy = H - 60
    body = pygame.Rect(cx - 45, cy - 18, 90, 36)
    pygame.draw.rect(screen, (210, 30, 30), body)
    pygame.draw.rect(screen, (20, 20, 20), (cx - 50, cy + 10, 20, 12))
    pygame.draw.rect(screen, (20, 20, 20), (cx + 30, cy + 10, 20, 12))


def default_track_path():
    # Picked when launched with no arguments at all, e.g. from the Maemo
    # desktop icon: lowest-numbered .trk next to game.py is the "main" course.
    here = os.path.dirname(os.path.abspath(__file__))
    track_dir = os.path.join(here, 'tracks')
    candidates = [f for f in os.listdir(track_dir) if f.endswith('.trk')]
    candidates.sort()
    if not candidates:
        return None
    return os.path.join(track_dir, candidates[0])


def main():
    if len(sys.argv) < 2:
        track_path = default_track_path()
        if not track_path:
            sys.stderr.write('usage: python2.5 game.py <track.trk> [tilt_source] [telemetry_csv] [timeout_s]\n')
            return 2
    else:
        track_path = sys.argv[1]
    tilt_path = sys.argv[2] if len(sys.argv) > 2 else ACCEL_PATH
    # No cap by default: a human race ends on 'finish' or 'quit'. The 4th arg
    # is only for scripted/bot runs (bot_steer.py, tools/racer_fps.py) that
    # need a hard stop if the bot never reaches the finish line.
    timeout_s = float(sys.argv[4]) if len(sys.argv) > 4 else None

    trk = track.load(track_path)
    errors = track.validate(trk)
    if errors:
        i = 0
        while i < len(errors):
            sys.stdout.write(errors[i] + '\n')
            i += 1
        return 2

    telemetry_path = sys.argv[3] if len(sys.argv) > 3 else default_telemetry_path(track_path, trk)

    # Spawned before pygame.init() / display setup on purpose - see
    # start_buzz_helper()'s comment.
    buzz_helper = start_buzz_helper()

    pygame.init()
    pygame.mouse.set_visible(False)
    screen = pygame.display.set_mode((W, H), pygame.FULLSCREEN, 16)
    bg = build_theme_background(trk.get('theme', DEFAULT_THEME))
    backdrop = build_backdrop(trk.get('theme', DEFAULT_THEME))
    palette = build_palette(trk.get('theme', DEFAULT_THEME))
    sprite_pal = palette[2]
    tx = Telemetry(telemetry_path)

    player_z = 0.0
    player_x = 0.0
    speed = 0.0

    obstacle_hit_flags = [0] * len(trk['obstacles'])
    traffic_cooldowns = [0.0] * len(trk['traffic'])

    last_tilt = (0, 0, -1000)
    t0 = time.time()
    last_frame_t = t0
    last_sample = t0
    last_second = t0

    sec_frames = 0
    frames = 0
    hits = 0
    outcome = ''
    pending_event = ''

    calibration_sum = 0.0
    calibration_count = 0
    calibrated = 0
    level_x = 0.0
    tilt_history = []

    # Zone buzzes (curb/grass) are sustained states, not one-shot events, so
    # they're debounced on a cooldown instead of firing (and forking a fresh
    # dbus-send process) every single frame - that alone cut avg fps from
    # ~49 to ~18 in an on-device bot test before this fix.
    ZONE_BUZZ_COOLDOWN = 0.35
    next_zone_buzz = 0.0

    try:
        while not outcome:
            frame_now = time.time()
            race_t = frame_now - t0
            if timeout_s is not None and race_t >= timeout_s:
                outcome = 'timeout'
                break

            for e in pygame.event.get():
                if e.type == pygame.QUIT or e.type == pygame.KEYDOWN or e.type == pygame.MOUSEBUTTONDOWN:
                    outcome = 'quit'
                    break
            if outcome:
                break

            dt = frame_now - last_frame_t
            if dt < 0.0:
                dt = 0.0
            if dt > 0.05:
                dt = 0.05
            last_frame_t = frame_now

            last_tilt = read_tilt(tilt_path, last_tilt)
            raw_x, raw_y, raw_z = last_tilt

            # Steering reads raw_x, not raw_y: measured on-device (2026-09-07)
            # holding the phone landscape (as this game requires) and rolling
            # it left made raw_x swing from ~30 to ~650+ mg while raw_y/raw_z
            # stayed within their resting noise band. raw_y was fremarble's
            # axis for its flat-on-a-table tilt game; a landscape-held racer
            # needs the roll axis instead, which is raw_x on this device/grip.
            if not calibrated:
                calibration_sum += raw_x
                calibration_count += 1
                if race_t >= CALIBRATION_WINDOW and calibration_count > 0:
                    level_x = calibration_sum / calibration_count
                    calibrated = 1
                    tilt_history = []
                steer_tilt = 0.0
            else:
                adj_x = raw_x - level_x
                tilt_history.append(adj_x)
                if len(tilt_history) > 3:
                    del tilt_history[0]
                s = 0.0
                i = 0
                while i < len(tilt_history):
                    s += tilt_history[i]
                    i += 1
                steer_tilt = s / len(tilt_history)
                if steer_tilt > -TILT_DEAD_ZONE and steer_tilt < TILT_DEAD_ZONE:
                    steer_tilt = 0.0

            i = 0
            while i < len(traffic_cooldowns):
                if traffic_cooldowns[i] > 0.0:
                    traffic_cooldowns[i] -= dt
                i += 1

            if calibrated:
                curve, _, width, _ = track.segment_at(trk, player_z)

                # Zone is judged on this frame's *incoming* position, before the car
                # moves, so a hard-braking penalty actually slows this frame's travel
                # instead of only being visible a frame late in telemetry.
                abs_x = abs(player_x)
                off_road = abs_x > width * 1.0
                in_grass = abs_x > width * GRASS_ZONE
                in_rumble = (not in_grass) and abs_x > width * RUMBLE_ZONE

                target_max = OFFROAD_MAX_SPEED if off_road else MAX_SPEED
                if speed < target_max:
                    speed += ACCEL * dt
                    if speed > target_max:
                        speed = target_max
                else:
                    speed -= BRAKE_DECEL * 0.5 * dt
                    if speed < target_max:
                        speed = target_max

                buzz_key = None
                if in_grass:
                    speed -= BRAKE_DECEL * dt
                    if not pending_event:
                        pending_event = 'grass'
                    if frame_now >= next_zone_buzz:
                        buzz_key = 'grass'
                        next_zone_buzz = frame_now + ZONE_BUZZ_COOLDOWN
                elif in_rumble:
                    if not pending_event:
                        pending_event = 'curb'
                    if frame_now >= next_zone_buzz:
                        buzz_key = 'curb'
                        next_zone_buzz = frame_now + ZONE_BUZZ_COOLDOWN
                if speed < 0.0:
                    speed = 0.0

                speed_frac = speed / MAX_SPEED
                if speed_frac < STEER_MIN_SPEED_FRAC:
                    speed_frac = STEER_MIN_SPEED_FRAC
                # Rolling the device left (raw_x rises, see calibration above)
                # steers left, i.e. decreases player_x - hence the minus sign.
                player_x -= steer_tilt * STEER_GAIN * speed_frac * dt
                player_x -= curve * speed * CENTRIFUGAL * dt

                # Hard bound so a missed corner is recoverable instead of an
                # unbounded drift into open space.
                max_drift = width * 3.0
                if player_x > max_drift:
                    player_x = max_drift
                elif player_x < -max_drift:
                    player_x = -max_drift

                player_z += speed * dt

                oi, okind = find_obstacle_hit(trk['obstacles'], player_z, player_x, trk, obstacle_hit_flags)
                if oi >= 0:
                    speed *= HIT_SPEED_SCALE
                    hits += 1
                    buzz_key = 'hit'
                    pending_event = 'hit-' + okind

                ti, tkind = find_traffic_hit(trk['traffic'], player_z, player_x, race_t, trk, traffic_cooldowns)
                if ti >= 0:
                    speed *= HIT_SPEED_SCALE
                    hits += 1
                    buzz_key = 'hit'
                    pending_event = 'hit-' + tkind

                if buzz_key:
                    buzz_event(buzz_helper, buzz_key)

            if player_z >= trk['lap_length']:
                outcome = 'finish'
                buzz_event(buzz_helper, 'finish')

            base_index, cam_y, cam_z, curve_off = draw_road(
                screen, bg, backdrop, trk, palette, player_z, player_x)
            n_curve = len(curve_off)

            # Sprites are collected first and drawn far-to-near afterwards.
            # Drawing them in track order let a distant car paint over a near
            # one; they also take the same distance haze as the road, or a
            # full-saturation cone at the horizon reads as nearer than the
            # road it is standing on.
            sprites = []
            i = 0
            while i < len(trk['obstacles']):
                seg_i, offset, kind = trk['obstacles'][i]
                obs_z = seg_i * SEGMENT_LENGTH + SEGMENT_LENGTH / 2.0
                if obs_z >= player_z and obs_z < player_z + DRAW_DISTANCE * SEGMENT_LENGTH:
                    _, oy, owidth, _ = track.segment_at(trk, obs_z)
                    sprites.append((obs_z, offset * owidth, oy, kind))
                i += 1

            i = 0
            while i < len(trk['traffic']):
                seg_i, offset, tspeed, kind = trk['traffic'][i]
                base_z = seg_i * SEGMENT_LENGTH
                car_z = traffic_world_z(base_z, tspeed, race_t, trk['lap_length'])
                if car_z >= player_z and car_z < player_z + DRAW_DISTANCE * SEGMENT_LENGTH:
                    _, ty, twidth, _ = track.segment_at(trk, car_z)
                    sprites.append((car_z, offset * twidth, ty, kind))
                i += 1

            sprites.sort()
            i = len(sprites) - 1
            while i >= 0:
                sz, sx, sy, kind = sprites[i]
                bi = int((sz - player_z) / SEGMENT_LENGTH)
                if bi < 0:
                    bi = 0
                elif bi >= DRAW_DISTANCE:
                    bi = DRAW_DISTANCE - 1
                # Sprites ride the same per-frame curve accumulator as the
                # road bands, or they would sit on the camera's straight-ahead
                # line while the road they belong to bends away from it.
                if n_curve == 0:
                    coff = 0.0
                elif bi >= n_curve:
                    coff = curve_off[n_curve - 1]
                else:
                    coff = curve_off[bi]
                sp = sprite_pal[bi]
                draw_sprite(screen, coff + sx - player_x, sy, sz, cam_y, cam_z,
                            sp.get(kind, sp['']), OBSTACLE_HALF_WIDTH)
                i -= 1

            draw_car(screen, player_x / (trk['width'] * 2.0))
            pygame.display.flip()

            frames += 1
            sec_frames += 1

            sample_now = time.time()
            if sample_now - last_sample >= 0.1:
                tx.sample(sample_now - t0, player_z, speed, player_x, raw_x, pending_event)
                pending_event = ''
                last_sample = sample_now
            if sample_now - last_second >= 1.0:
                tx.second(sample_now - t0, sec_frames / (sample_now - last_second))
                sec_frames = 0
                last_second = sample_now

        elapsed = time.time() - t0
        avg_fps = frames / elapsed if elapsed > 0.0 else 0.0
        if not outcome:
            outcome = 'timeout'

        tx.close({'outcome': outcome, 'elapsed': elapsed, 'hits': hits, 'par': trk['par'],
                  'frames': frames, 'avg_fps': avg_fps})
        pygame.quit()
        sys.stdout.write('RESULT outcome=%s elapsed=%.1f hits=%d par=%g frames=%d avg_fps=%.1f\n' % (
            outcome, elapsed, hits, trk['par'], frames, avg_fps))
        sys.stdout.flush()
        if outcome == 'finish':
            return 0
        if outcome == 'quit':
            return 1
        if outcome == 'timeout':
            return 3
        return 1
    finally:
        # Patterns are self-terminating (fixed repeat counts, see mce.ini), but
        # explicitly deactivate on any exit path (including exceptions) so a
        # crash mid-pattern can't leave the vibrator buzzing after quit. This
        # runs once at shutdown, not per-frame, so forking directly here
        # (rather than through the helper, which we're closing anyway) is fine.
        for pattern_name in set(VIBRATOR_PATTERNS.values()):
            try:
                subprocess.Popen((
                    'dbus-send', '--system', '--type=method_call',
                    '--dest=com.nokia.mce', '/com/nokia/mce/request',
                    'com.nokia.mce.request.req_vibrator_pattern_deactivate',
                    'string:' + pattern_name,
                ), stdout=DEVNULL, stderr=DEVNULL)
            except Exception:
                pass
        stop_buzz_helper(buzz_helper)


if __name__ == '__main__':
    sys.exit(main())
