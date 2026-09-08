# window.py - the segment window: the slice of road around the camera.
# Python 2.5 safe. See docs/INFINITE-ROAD-SPEC.md section 5.
#
# game.py used to index one flat list of every segment of the lap. A journey
# has no end, so the renderer, physics and collision code now index a window
# that a generator fills just ahead of the camera and that is trimmed just
# behind it. A finite .trk is the same structure with the generator absent
# and a finish line present, so there is one render path, not two.

import track

SEGMENT_LENGTH = track.SEGMENT_LENGTH
DRAW_DISTANCE = track.DRAW_DISTANCE
LOOKAHEAD = 450              # one longest chunk, on top of DRAW_DISTANCE
KEEP_BEHIND = 20             # segments kept behind the player
TRIM_BATCH = 40              # trim this many at once: del segments[:k] is O(n)


class Window(object):

    def __init__(self, generator=None):
        self.base = 0                # absolute index of segments[0]
        self.segments = []
        self.obstacles = []          # [abs_seg, offset, kind, hit_flag]
        self.traffic = []            # (seg, offset, speed, kind) - .trk lap traffic only
        self.chunk_log = []          # (abs_seg_start, region, chunk_id, motif, kind)
        self.lap_length = 0.0        # > 0 only for a finite track
        self.finish = None
        self.width = track.DEFAULT_WIDTH
        self.par = 0.0
        self.name = ''
        self.gen = generator
        self.pending = []            # stretches of the chunk being expanded
        self.y = 0.0
        self.heading = 0.0
        self.end_width = track.DEFAULT_WIDTH
        self.region = None

    # ---- construction ---------------------------------------------------

    def from_track(trk):
        """Wrap a loaded .trk (already padded with its runway)."""
        w = Window()
        w.segments = trk['segments']
        w.lap_length = trk['lap_length']
        w.finish = trk['finish_segment']
        w.width = trk['width']
        w.par = trk['par']
        w.name = trk.get('name', '')
        w.traffic = list(trk['traffic'])
        i = 0
        while i < len(trk['obstacles']):
            seg_i, offset, kind = trk['obstacles'][i]
            w.obstacles.append([seg_i, offset, kind, 0])
            i += 1
        w.chunk_log.append((0, trk.get('theme', ''), 0, 'track', 'track'))
        if w.segments:
            w.region = w.segments[0]['region']
        return w
    from_track = staticmethod(from_track)

    # ---- lookups --------------------------------------------------------

    def segment_at(self, z):
        """(curve, y, width, heading) at world z, interpolated like track.segment_at."""
        return track.segment_at_list(self.segments, self.base, z)

    def region_at(self, z):
        idx = int(z / SEGMENT_LENGTH) - self.base
        if idx < 0:
            idx = 0
        elif idx >= len(self.segments):
            idx = len(self.segments) - 1
        return self.segments[idx]['region']

    def ahead(self, z):
        """Segments available beyond the player's segment."""
        return len(self.segments) - (int(z / SEGMENT_LENGTH) - self.base)

    # ---- generation -----------------------------------------------------

    def _take_chunk(self):
        chunk = self.gen.next_chunk()
        self.chunk_log.append(self.gen.chunk_log[-1])
        i = 0
        while i < len(chunk['obstacles']):
            local, offset, kind = chunk['obstacles'][i]
            self.obstacles.append([chunk['start'] + local, offset, kind, 0])
            i += 1
        i = 0
        while i < len(chunk['stretches']):
            self.pending.append((chunk['stretches'][i], chunk['region']))
            i += 1

    def _expand_one(self):
        if not self.pending:
            self._take_chunk()
        (count, curve, hill, w1), region = self.pending.pop(0)
        self.y, self.heading = track.expand_stretch(
            self.segments, count, curve, hill, self.end_width, w1,
            self.y, self.heading, region)
        self.end_width = w1

    def feed(self, z, budget=1):
        """Expand up to `budget` stretches if the road ahead is short.

        Returns 1 if the window is starving (less than DRAW_DISTANCE ahead),
        which the caller logs as a telemetry event. One stretch per frame is
        at least 10 segments per frame against under 3 segments of travel,
        so a healthy window never starves; a starve means generation fell
        behind or the budget was too small on this hardware.
        """
        if self.gen is None:
            return 0
        need = int(z / SEGMENT_LENGTH) - self.base + DRAW_DISTANCE + LOOKAHEAD
        n = 0
        while len(self.segments) < need and n < budget:
            self._expand_one()
            n += 1
        if self.ahead(z) < DRAW_DISTANCE:
            return 1
        return 0

    def trim(self, z):
        """Drop segments and obstacles well behind the player; bump base."""
        behind = int(z / SEGMENT_LENGTH) - self.base
        if behind > KEEP_BEHIND + TRIM_BATCH:
            drop = behind - KEEP_BEHIND
            del self.segments[:drop]
            self.base += drop
            keep = []
            i = 0
            while i < len(self.obstacles):
                if self.obstacles[i][0] >= self.base:
                    keep.append(self.obstacles[i])
                i += 1
            self.obstacles = keep

    def prime(self):
        """Fill the window before the first frame."""
        self.feed(0.0, 100000)
        if self.segments:
            self.region = self.segments[0]['region']
            self.width = self.segments[0]['width']
        return self


def journey(seed):
    import journey as journey_mod
    return Window(journey_mod.Generator(seed)).prime()
