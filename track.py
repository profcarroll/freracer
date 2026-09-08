# track.py - load, build and validate freracer .trk files
# Also the segment expander the infinite road shares (expand_stretch).
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


def expand_stretch(out, count, curve, hill, width0, width1, y, heading, region):
    """Append one ROAD stretch's segments to `out`. Returns (y, heading) after it.

    Each segment dict: {'curve', 'y', 'width', 'heading', 'region'}.
    curve is eased in over the first third of the stretch, held over the
    middle third and eased back out over the last third; height is eased
    with smoothstep over the whole stretch; width ramps linearly from width0
    to width1. Every stretch therefore starts and ends at curve ~0 with y
    continuous, so any two stretches join without a kink - the property the
    infinite road's chunk stitching rests on (docs/INFINITE-ROAD-SPEC.md 2).

    'heading' is the running sum of curve up to (not including) this
    segment: what the renderer pans the horizon backdrop by. It replaces the
    absolute centreline x an earlier version integrated here, which grows
    without bound on an infinite road and which nothing projects any more.
    """
    count = int(count)
    third = count / 3.0
    if third < 1.0:
        third = 1.0
    j = 0
    while j < count:
        t = (j + 1) / float(count)
        if j < third:
            ramp = _ease(j / third)
        elif j > count - third:
            ramp = _ease((count - j) / third)
        else:
            ramp = 1.0
        seg_curve = curve * ramp
        out.append({'curve': seg_curve,
                    'y': y + hill * _ease(t),
                    'width': width0 + (width1 - width0) * t,
                    'heading': heading,
                    'region': region})
        heading += seg_curve
        j += 1
    return y + hill, heading


def _build_segments(roads, width, region='track'):
    """Expand ROAD stretches into a flat segment list.

    Each road is (segments, curve, hill) or (segments, curve, hill, width),
    where a fourth element is the width the stretch ramps *to*; without one
    the stretch keeps the width it started at. Widths in world units are
    half-widths, as everywhere else.
    """
    segments = []
    y = 0.0
    heading = 0.0
    w = width
    i = 0
    while i < len(roads):
        road = roads[i]
        w1 = w
        if len(road) > 3:
            w1 = road[3]
        y, heading = expand_stretch(segments, road[0], road[1], road[2],
                                    w, w1, y, heading, region)
        w = w1
        i += 1
    return segments


def _pad_runway(segments, count):
    """Append flat straight segments after the last ROAD so the renderer always
    has DRAW_DISTANCE segments to look ahead, even right at the finish line."""
    if not segments:
        return
    last = segments[-1]
    i = 0
    while i < count:
        segments.append({'curve': 0.0, 'y': last['y'], 'width': last['width'],
                         'heading': last['heading'], 'region': last['region']})
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

    # WIDTH before the first ROAD sets the starting half-width. WIDTH between
    # ROAD lines makes the *next* stretch ramp linearly to the new value -
    # how an exported journey carries a region's width change across.
    pending_width = None
    cur_width = DEFAULT_WIDTH
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
            if trk['roads']:
                pending_width = float(parts[1])
            else:
                trk['width'] = float(parts[1])
                cur_width = trk['width']
        elif kw == 'ROAD':
            if pending_width is not None:
                cur_width = pending_width
                pending_width = None
            trk['roads'].append((int(parts[1]), float(parts[2]), float(parts[3]), cur_width))
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

    trk['segments'] = _build_segments(trk['roads'], trk['width'], trk['theme'])
    if trk['finish_segment'] is None:
        trk['finish_segment'] = len(trk['segments'])
    trk['lap_length'] = trk['finish_segment'] * SEGMENT_LENGTH
    _pad_runway(trk['segments'], DRAW_DISTANCE)
    return trk


def segment_at(trk, z_abs):
    """Return (curve, y, width, heading) interpolated at world distance z_abs."""
    return segment_at_list(trk['segments'], 0, z_abs)


def segment_at_list(segments, base, z_abs):
    """segment_at over a window: `base` is the absolute index of segments[0]."""
    n = len(segments)
    idx = int(z_abs / SEGMENT_LENGTH) - base
    if idx < 0:
        idx = 0
    if idx >= n - 1:
        s = segments[n - 1]
        return s['curve'], s['y'], s['width'], s['heading']
    frac = (z_abs - (idx + base) * SEGMENT_LENGTH) / SEGMENT_LENGTH
    a = segments[idx]
    b = segments[idx + 1]
    y = a['y'] + (b['y'] - a['y']) * frac
    return a['curve'], y, a['width'], a['heading']


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

    errors.extend(validate_segments(segments, 0))

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


MAX_CURVE_JUMP = 4.0
MAX_WIDTH_STEP = 20.0          # a WIDTH ramp of 200 over 40 segments is 5


def validate_segments(segments, base):
    """Continuity checks shared by .trk validation and the journey window."""
    errors = []
    prev = None
    i = 0
    while i < len(segments):
        seg = segments[i]
        if prev is not None:
            jump = seg['curve'] - prev['curve']
            if jump > MAX_CURVE_JUMP or jump < -MAX_CURVE_JUMP:
                errors.append('segment %d has a curve discontinuity (%.2f)' % (base + i, jump))
            step = seg['width'] - prev['width']
            if step > MAX_WIDTH_STEP or step < -MAX_WIDTH_STEP:
                errors.append('segment %d has a width step (%.1f)' % (base + i, step))
        prev = seg
        i += 1
    return errors


def track_length(trk):
    return len(trk['segments']) * SEGMENT_LENGTH
