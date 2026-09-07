# track.py - load, build and validate freracer .trk files
# Python 2.5 safe: no json, no with, no print(), no dict comprehensions.

SCREEN_W = 800
SCREEN_H = 480
SEGMENT_LENGTH = 100.0
DEFAULT_WIDTH = 1000.0

# rendering / camera constants shared with game.py
DRAW_DISTANCE = 120          # segments drawn ahead of the camera; tuned on real N900
                              # hardware with tools/racer_fps.py: 160 -> 36 avg/19 worst
                              # fps, 120 -> ~50 avg/~49 worst fps. See README.
CAMERA_HEIGHT = 900.0
FIELD_OF_VIEW = 100.0        # degrees


def _ease(t):
    """Smoothstep 0..1 -> 0..1, used so ROAD stretches join without a kink."""
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return t * t * (3.0 - 2.0 * t)


def _build_segments(roads, width):
    """Expand ROAD <segments> <curve> <hill> stretches into a flat segment list.

    Each segment dict: {'curve': float, 'y': float, 'width': float, 'x': float}
    curve/height are eased in over the first third of a stretch, held over the
    middle third, and eased back out over the last third, so consecutive
    stretches never produce a discontinuous kink in the road. 'x' is the
    cumulative world-space lateral centreline position, integrated from curve
    once here so the renderer never has to re-derive it per frame.
    """
    segments = []
    y = 0.0
    i = 0
    while i < len(roads):
        count, curve, hill = roads[i]
        count = int(count)
        base_y = y
        j = 0
        while j < count:
            t = (j + 1) / float(count)
            third = count / 3.0
            if third < 1.0:
                third = 1.0
            if j < third:
                ramp = _ease(j / third)
            elif j > count - third:
                ramp = _ease((count - j) / third)
            else:
                ramp = 1.0
            seg_curve = curve * ramp
            seg_y = base_y + hill * _ease(t)
            segments.append({'curve': seg_curve, 'y': seg_y, 'width': width, 'x': 0.0})
            j += 1
        y = base_y + hill
        i += 1

    track_x = 0.0
    dx = 0.0
    i = 0
    while i < len(segments):
        segments[i]['x'] = track_x
        track_x += dx
        dx += segments[i]['curve']
        i += 1

    return segments


def _pad_runway(segments, count):
    """Append flat straight segments after the last ROAD so the renderer always
    has DRAW_DISTANCE segments to look ahead, even right at the finish line."""
    if not segments:
        return
    last = segments[-1]
    dx = 0.0
    if len(segments) >= 2:
        dx = last['x'] - segments[-2]['x']
    x = last['x'] + dx
    i = 0
    while i < count:
        segments.append({'curve': 0.0, 'y': last['y'], 'width': last['width'], 'x': x})
        x += dx
        i += 1


def load(path):
    f = open(path, 'r')
    try:
        lines = f.readlines()
    finally:
        f.close()

    trk = {
        'name': '',
        'theme': 'autumn-hills',
        'seed': 1,
        'par': 0.0,
        'width': DEFAULT_WIDTH,
        'roads': [],
        'obstacles': [],
        'traffic': [],
        'finish_segment': None,
    }

    for raw in lines:
        line = raw.strip()
        if not line or line[0] == '#':
            continue
        parts = line.split()
        kw = parts[0].upper()
        if kw == 'NAME':
            trk['name'] = line[len(parts[0]):].strip()
        elif kw == 'THEME':
            trk['theme'] = parts[1]
        elif kw == 'SEED':
            trk['seed'] = int(parts[1])
        elif kw == 'PAR':
            trk['par'] = float(parts[1])
        elif kw == 'WIDTH':
            trk['width'] = float(parts[1])
        elif kw == 'ROAD':
            trk['roads'].append((int(parts[1]), float(parts[2]), float(parts[3])))
        elif kw == 'OBSTACLE':
            trk['obstacles'].append(
                (int(parts[1]), float(parts[2]), parts[3])
            )
        elif kw == 'TRAFFIC':
            trk['traffic'].append(
                (int(parts[1]), float(parts[2]), float(parts[3]), parts[4])
            )
        elif kw == 'FINISH':
            trk['finish_segment'] = int(parts[1])
        # unknown directives are ignored on purpose

    trk['segments'] = _build_segments(trk['roads'], trk['width'])
    if trk['finish_segment'] is None:
        trk['finish_segment'] = len(trk['segments'])
    trk['lap_length'] = trk['finish_segment'] * SEGMENT_LENGTH
    _pad_runway(trk['segments'], DRAW_DISTANCE)
    return trk


def segment_at(trk, z_abs):
    """Return (curve, y, width, x) interpolated at world distance z_abs."""
    segments = trk['segments']
    n = len(segments)
    idx = int(z_abs / SEGMENT_LENGTH)
    if idx < 0:
        idx = 0
    if idx >= n - 1:
        s = segments[n - 1]
        return s['curve'], s['y'], s['width'], s['x']
    frac = (z_abs - idx * SEGMENT_LENGTH) / SEGMENT_LENGTH
    a = segments[idx]
    b = segments[idx + 1]
    y = a['y'] + (b['y'] - a['y']) * frac
    x = a['x'] + (b['x'] - a['x']) * frac
    return a['curve'], y, a['width'], x


OBSTACLE_TYPES = ('rock', 'cone', 'barrier', 'tree-stump')
TRAFFIC_TYPES = ('sedan', 'truck', 'tractor')


def validate(trk):
    errors = []
    segments = trk.get('segments', [])
    n = len(segments)

    if n == 0:
        errors.append('track has no ROAD segments')
        return errors

    if trk.get('par', 0.0) <= 0.0:
        errors.append('missing or non-positive PAR')

    finish = trk.get('finish_segment')
    if finish is None or finish <= 0 or finish > n:
        errors.append('FINISH segment out of range (0..%d)' % n)

    prev_curve = None
    i = 0
    while i < n:
        seg = segments[i]
        if prev_curve is not None:
            jump = seg['curve'] - prev_curve
            if jump > 4.0 or jump < -4.0:
                errors.append('segment %d has a curve discontinuity (%.2f)' % (i, jump))
        prev_curve = seg['curve']
        i += 1

    i = 0
    while i < len(trk.get('obstacles', [])):
        seg_i, offset, kind = trk['obstacles'][i]
        if seg_i < 0 or seg_i >= n:
            errors.append('OBSTACLE %d is out of range (0..%d)' % (seg_i, n - 1))
        if offset < -1.0 or offset > 1.0:
            errors.append('OBSTACLE %d has offset out of range -1..1' % seg_i)
        if kind not in OBSTACLE_TYPES:
            errors.append('OBSTACLE %d has unknown type %s' % (seg_i, kind))
        i += 1

    i = 0
    while i < len(trk.get('traffic', [])):
        seg_i, offset, speed, kind = trk['traffic'][i]
        if seg_i < 0 or seg_i >= n:
            errors.append('TRAFFIC %d is out of range (0..%d)' % (seg_i, n - 1))
        if offset < -1.0 or offset > 1.0:
            errors.append('TRAFFIC %d has offset out of range -1..1' % seg_i)
        if kind not in TRAFFIC_TYPES:
            errors.append('TRAFFIC %d has unknown type %s' % (seg_i, kind))
        i += 1

    if not trk.get('name'):
        errors.append('missing NAME')

    return errors


def track_length(trk):
    return len(trk['segments']) * SEGMENT_LENGTH
