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
        'sky': (255, 178, 102),
        'sky2': (255, 214, 153),
        'grass': (90, 110, 40),
        'grass2': (104, 128, 46),
    },
    'dusk-city': {
        'sky': (40, 30, 70),
        'sky2': (90, 60, 110),
        'grass': (30, 30, 34),
        'grass2': (36, 36, 40),
    },
    'coast': {
        'sky': (140, 200, 235),
        'sky2': (190, 225, 245),
        'grass': (60, 140, 90),
        'grass2': (70, 150, 100),
    },
}
DEFAULT_THEME = 'autumn-hills'

ROAD_COLOR = (60, 60, 66)
ROAD_COLOR2 = (100, 100, 108)
RUMBLE_LIGHT = (200, 60, 60)
RUMBLE_DARK = (230, 230, 230)
LANE_COLOR = (230, 220, 60)
POLE_LIGHT = (220, 40, 40)
POLE_DARK = (240, 240, 240)
POLE_INTERVAL = 5             # segments between roadside marker poles (500 world units)
POLE_OFFSET = 1.22            # fraction of half-width, just outside the rumble strip
POLE_HALF_WIDTH = 28.0
POLE_HEIGHT = 260.0

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


def buzz_pattern(name):
    # /sys/class/leds/twl4030:vibrator/brightness (write_vibrator, above) is
    # root-only (0644, root:root); a game launched from the Hildon desktop
    # runs as the unprivileged 'user' account and silently can't write it -
    # haptics never actually fired. write_vibrator() is kept only in case a
    # future root-run mode wants it. The permission-safe path is MCE's own
    # vibrator-pattern D-Bus API, which 'user' can call directly (verified:
    # req_vibrator_pattern_activate works unprivileged). Patterns are
    # named/fixed (see /etc/mce/mce.ini [VibraPatternRX51]) rather than
    # arbitrary durations, so events are mapped to the closest-feeling
    # built-in pattern instead of a custom on/off timing.
    try:
        subprocess.Popen((
            'dbus-send', '--system', '--type=method_call',
            '--dest=com.nokia.mce', '/com/nokia/mce/request',
            'com.nokia.mce.request.req_vibrator_pattern_activate',
            'string:' + name,
        ), stdout=DEVNULL, stderr=DEVNULL)
    except Exception:
        pass


def buzz_event(event_name):
    pattern = VIBRATOR_PATTERNS.get(event_name)
    if pattern:
        buzz_pattern(pattern)



def project(world_x, world_y, world_z, cam_x, cam_y, cam_z, road_width):
    dz = world_z - cam_z
    if dz < 1.0:
        dz = 1.0
    scale = CAMERA_DEPTH / dz
    screen_x = (W / 2.0) + scale * (world_x - cam_x) * (W / 2.0)
    screen_y = (H / 2.0) - scale * (world_y - cam_y) * (H / 2.0)
    screen_w = scale * road_width * (W / 2.0)
    return screen_x, screen_y, screen_w, scale


def build_theme_background(theme_name):
    theme = THEMES.get(theme_name, THEMES[DEFAULT_THEME])
    bg = pygame.Surface((W, H)).convert()
    horizon = H / 2
    i = 0
    while i < horizon:
        t = i / float(horizon)
        r = int(theme['sky'][0] + (theme['sky2'][0] - theme['sky'][0]) * t)
        g = int(theme['sky'][1] + (theme['sky2'][1] - theme['sky'][1]) * t)
        b = int(theme['sky'][2] + (theme['sky2'][2] - theme['sky'][2]) * t)
        pygame.draw.line(bg, (r, g, b), (0, i), (W, i))
        i += 1
    pygame.draw.rect(bg, theme['grass'], (0, horizon, W, H - horizon))
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
                _, _, width, cx = track.segment_at(trk, obs_z)
                obs_x = cx + offset * width
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
            _, _, width, cx = track.segment_at(trk, car_z)
            car_x = cx + offset * width
            if abs(player_x - car_x) < (CAR_HALF_WIDTH + OBSTACLE_HALF_WIDTH):
                cooldowns[i] = 2.0
                return i, kind
        i += 1
    return -1, None


def draw_road(screen, bg, trk, player_z, player_x):
    screen.blit(bg, (0, 0))
    segments = trk['segments']
    n = len(segments)
    theme = THEMES.get(trk.get('theme', DEFAULT_THEME), THEMES[DEFAULT_THEME])

    base_index = int(player_z / SEGMENT_LENGTH)
    if base_index >= n - 1:
        base_index = n - 2
    if base_index < 0:
        base_index = 0

    _, player_y, _, _ = track.segment_at(trk, player_z)
    cam_x = player_x
    cam_y = player_y + CAMERA_HEIGHT
    cam_z = player_z

    max_y = H
    i = DRAW_DISTANCE - 1
    while i >= 0:
        idx = base_index + i
        if idx >= n - 1:
            i -= 1
            continue
        a = segments[idx]
        b = segments[idx + 1]
        z1 = idx * SEGMENT_LENGTH
        z2 = (idx + 1) * SEGMENT_LENGTH
        if z2 <= cam_z:
            i -= 1
            continue

        x1, y1, w1, s1 = project(a['x'], a['y'], z1, cam_x, cam_y, cam_z, a['width'])
        x2, y2, w2, s2 = project(b['x'], b['y'], z2, cam_x, cam_y, cam_z, b['width'])

        if y2 >= y1 or y2 >= max_y:
            i -= 1
            continue

        band = (idx // 3) % 2
        road_color = ROAD_COLOR if band == 0 else ROAD_COLOR2
        rumble_color = RUMBLE_LIGHT if band == 0 else RUMBLE_DARK
        shoulder_color = theme['grass'] if band == 0 else theme['grass2']

        # Shoulder: a banded strip wider than the rumble strip, so the ground
        # right next to the road visibly scrolls past too - without this the
        # whole periphery was one flat static colour and nothing but the road
        # itself read as "moving", which is why the road edge was hard to place.
        sw1 = w1 * (RUMBLE_ZONE + 1.2)
        sw2 = w2 * (RUMBLE_ZONE + 1.2)
        pygame.draw.polygon(screen, shoulder_color, (
            (x1 - sw1, y1), (x1 + sw1, y1), (x2 + sw2, y2), (x2 - sw2, y2)))

        rw1 = w1 * RUMBLE_ZONE
        rw2 = w2 * RUMBLE_ZONE
        pygame.draw.polygon(screen, rumble_color, (
            (x1 - rw1, y1), (x1 + rw1, y1), (x2 + rw2, y2), (x2 - rw2, y2)))
        pygame.draw.polygon(screen, road_color, (
            (x1 - w1, y1), (x1 + w1, y1), (x2 + w2, y2), (x2 - w2, y2)))

        if idx % 6 < 3:
            lw1 = w1 * 0.03
            lw2 = w2 * 0.03
            pygame.draw.polygon(screen, LANE_COLOR, (
                (x1 - lw1, y1), (x1 + lw1, y1), (x2 + lw2, y2), (x2 - lw2, y2)))

        if idx % POLE_INTERVAL == 0:
            pole_color = POLE_LIGHT if (idx // POLE_INTERVAL) % 2 == 0 else POLE_DARK
            pw1 = w1 * POLE_OFFSET
            draw_pole(screen, a['x'] - pw1, a['y'], z1, cam_x, cam_y, cam_z,
                      pole_color, POLE_HALF_WIDTH, POLE_HEIGHT)
            draw_pole(screen, a['x'] + pw1, a['y'], z1, cam_x, cam_y, cam_z,
                      pole_color, POLE_HALF_WIDTH, POLE_HEIGHT)

        max_y = y1
        i -= 1

    return base_index, cam_x, cam_y, cam_z


def draw_sprite(screen, world_x, world_y, world_z, cam_x, cam_y, cam_z, color, half_w):
    if world_z <= cam_z:
        return
    x, y, w, scale = project(world_x, world_y, world_z, cam_x, cam_y, cam_z, half_w)
    if scale <= 0.0:
        return
    h = w * 1.4
    rect = pygame.Rect(int(x - w), int(y - h), int(w * 2), int(h))
    if rect.bottom < 0 or rect.top > H:
        return
    pygame.draw.rect(screen, color, rect)


def draw_pole(screen, world_x, ground_y, world_z, cam_x, cam_y, cam_z, color, half_w, height):
    # Roadside marker post: projects the ground point and a point `height`
    # above it separately (unlike draw_sprite, whose height is tied to its
    # projected half-width) so poles read as a consistent physical size
    # planted on the shoulder, not a blob scaled only by lane width.
    if world_z <= cam_z:
        return
    bx, by, bw, bscale = project(world_x, ground_y, world_z, cam_x, cam_y, cam_z, half_w)
    if bscale <= 0.0:
        return
    _, ty, _, _ = project(world_x, ground_y + height, world_z, cam_x, cam_y, cam_z, half_w)
    top = int(ty)
    bottom = int(by)
    if bottom <= top:
        return
    rect = pygame.Rect(int(bx - bw), top, int(bw * 2), bottom - top)
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

    pygame.init()
    pygame.mouse.set_visible(False)
    screen = pygame.display.set_mode((W, H), pygame.FULLSCREEN, 16)
    bg = build_theme_background(trk.get('theme', DEFAULT_THEME))
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
                    buzz_event(buzz_key)

            if player_z >= trk['lap_length']:
                outcome = 'finish'
                buzz_event('finish')

            base_index, cam_x, cam_y, cam_z = draw_road(screen, bg, trk, player_z, player_x)

            i = 0
            while i < len(trk['obstacles']):
                seg_i, offset, kind = trk['obstacles'][i]
                obs_z = seg_i * SEGMENT_LENGTH + SEGMENT_LENGTH / 2.0
                if obs_z >= player_z and obs_z < player_z + DRAW_DISTANCE * SEGMENT_LENGTH:
                    _, oy, owidth, ocx = track.segment_at(trk, obs_z)
                    obs_x = ocx + offset * owidth
                    draw_sprite(screen, obs_x, oy, obs_z, cam_x, cam_y, cam_z,
                                OBSTACLE_COLORS.get(kind, (150, 150, 150)), OBSTACLE_HALF_WIDTH)
                i += 1

            i = 0
            while i < len(trk['traffic']):
                seg_i, offset, tspeed, kind = trk['traffic'][i]
                base_z = seg_i * SEGMENT_LENGTH
                car_z = traffic_world_z(base_z, tspeed, race_t, trk['lap_length'])
                if car_z >= player_z and car_z < player_z + DRAW_DISTANCE * SEGMENT_LENGTH:
                    _, ty, twidth, tcx = track.segment_at(trk, car_z)
                    car_x = tcx + offset * twidth
                    draw_sprite(screen, car_x, ty, car_z, cam_x, cam_y, cam_z,
                                TRAFFIC_COLORS.get(kind, (150, 150, 150)), OBSTACLE_HALF_WIDTH)
                i += 1

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
        # crash mid-pattern can't leave the vibrator buzzing after quit.
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


if __name__ == '__main__':
    sys.exit(main())
