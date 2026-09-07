"""A software stand-in for pygame, so game.py's renderer can be run off-device.

This exists because freracer spent two sessions tuning colours on a renderer
that was drawing one band per frame (see HANDOFF.md, session 3). The N900 is
the only machine in the project with pygame on it, so "does the frame look
right" was a question nobody could ask without walking to the device — and the
answer that came back, "the road is the wrong colour", was not the actual
problem. This module makes that question answerable from the laptop.

It implements only what game.py's draw path touches: Surface, Rect, fill,
blit, draw.line/rect/polygon, and enough of display/event/mouse to let the
module import. It is Python 3 (like tools/generate_track.py) and it is
deliberately dumb and slow — it renders correctness, not frames per second.
Nothing here runs on the device; tools/racer_fps.py is still the only thing
that can tell you about performance.

    python3 tools/render_shot.py tracks/001-autumn-hills.trk
"""
import struct
import zlib

FULLSCREEN = 1
QUIT = 12
KEYDOWN = 2
MOUSEBUTTONDOWN = 5


class Rect(object):
    def __init__(self, x, y=None, w=None, h=None):
        if y is None:
            x, y, w, h = x
        self.x, self.y, self.w, self.h = int(x), int(y), int(w), int(h)

    @property
    def top(self):
        return self.y

    @property
    def bottom(self):
        return self.y + self.h


class Surface(object):
    def __init__(self, size):
        self.w, self.h = int(size[0]), int(size[1])
        self.buf = bytearray(self.w * self.h * 3)
        self.calls = {'fill': 0, 'polygon': 0, 'line': 0, 'rect': 0, 'blit': 0}
        self.clip = None

    def convert(self):
        return self

    def get_width(self):
        return self.w

    def get_height(self):
        return self.h

    def set_clip(self, rect=None):
        self.clip = None if rect is None else (
            rect if isinstance(rect, Rect) else Rect(rect))

    def get_clip(self):
        return self.clip if self.clip is not None else Rect(0, 0, self.w, self.h)

    def _span(self, y, x0, x1, c):
        if y < 0 or y >= self.h:
            return
        cl = self.clip
        if cl is not None:
            if y < cl.y or y >= cl.y + cl.h:
                return
            x0 = max(x0, cl.x)
            x1 = min(x1, cl.x + cl.w)
        x0 = max(0, int(x0))
        x1 = min(self.w, int(x1))
        if x1 <= x0:
            return
        o = (y * self.w + x0) * 3
        self.buf[o:o + (x1 - x0) * 3] = bytes(c) * (x1 - x0)

    def fill(self, color, rect=None, flags=0):
        self.calls['fill'] += 1
        c = tuple(color[:3])
        r = Rect(0, 0, self.w, self.h) if rect is None else (
            rect if isinstance(rect, Rect) else Rect(rect))
        y = max(0, r.y)
        ymax = min(self.h, r.y + r.h)
        while y < ymax:
            self._span(y, r.x, r.x + r.w, c)
            y += 1

    def blit(self, other, pos, area=None):
        self.calls['blit'] += 1
        dx, dy = int(pos[0]), int(pos[1])
        cl = self.clip
        sy = 0
        while sy < other.h:
            ty = dy + sy
            if 0 <= ty < self.h and (cl is None or cl.y <= ty < cl.y + cl.h):
                x0 = max(0, dx)
                x1 = min(self.w, dx + other.w)
                if cl is not None:
                    x0 = max(x0, cl.x)
                    x1 = min(x1, cl.x + cl.w)
                if x1 > x0:
                    so = (sy * other.w + (x0 - dx)) * 3
                    to = (ty * self.w + x0) * 3
                    self.buf[to:to + (x1 - x0) * 3] = other.buf[so:so + (x1 - x0) * 3]
            sy += 1


class _Draw(object):
    def line(self, surf, color, p0, p1):
        surf.calls['line'] += 1
        surf._span(int(p0[1]), p0[0], p1[0], tuple(color[:3]))

    def rect(self, surf, color, r):
        surf.fill(color, r)
        surf.calls['rect'] += 1

    def polygon(self, surf, color, pts):
        # Even-odd scanline fill. game.py only draws convex quads and one
        # ridge polygon, but even-odd costs nothing extra and is harder to
        # get subtly wrong than a quad-specific path would be.
        surf.calls['polygon'] += 1
        c = tuple(color[:3])
        ys = [p[1] for p in pts]
        y = max(0, int(min(ys)))
        ymax = min(surf.h, int(max(ys)) + 1)
        n = len(pts)
        while y < ymax:
            yc = y + 0.5
            xs = []
            i = 0
            while i < n:
                ax, ay = pts[i]
                bx, by = pts[(i + 1) % n]
                if (ay <= yc < by) or (by <= yc < ay):
                    xs.append(ax + (yc - ay) * (bx - ax) / (by - ay))
                i += 1
            xs.sort()
            i = 0
            while i + 1 < len(xs):
                surf._span(y, round(xs[i]), round(xs[i + 1]), c)
                i += 2
            y += 1


draw = _Draw()


class _Display(object):
    def set_mode(self, size, flags=0, depth=0):
        return Surface(size)

    def flip(self):
        pass


class _Mouse(object):
    def set_visible(self, v):
        pass


class _Event(object):
    def get(self):
        return []


display = _Display()
mouse = _Mouse()
event = _Event()


def init():
    pass


def quit():
    pass


def save_png(surf, path):
    raw = b''
    y = 0
    while y < surf.h:
        raw += b'\x00' + bytes(surf.buf[y * surf.w * 3:(y + 1) * surf.w * 3])
        y += 1

    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data
                + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))

    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', surf.w, surf.h, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(raw, 6))
           + chunk(b'IEND', b''))
    f = open(path, 'wb')
    try:
        f.write(png)
    finally:
        f.close()
