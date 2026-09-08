import csv
import os

class Telemetry(object):
    def __init__(self, path):
        self.path = path
        self.f = None
        self.w = None
        self.open()

    def open(self):
        if self.f:
            return
        d = os.path.dirname(self.path)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        self.f = open(self.path, 'w')
        self.w = csv.writer(self.f)
        self.w.writerow(['t', 'z', 'speed', 'offset', 'tilt', 'event'])
        self.f.flush()

    def _write(self, row):
        self.w.writerow(row)
        self.f.flush()

    def sample(self, t, z, speed, offset, tilt, event):
        self._write([t, z, speed, offset, tilt, event])

    def second(self, t, fps):
        self._write([t, fps, '', '', '', 'fps'])

    def close(self, summary_dict):
        if not self.f:
            return
        items = sorted(summary_dict.items())
        s = []
        i = 0
        while i < len(items):
            k, v = items[i]
            s.append(str(k) + '=' + str(v))
            i += 1
        self._write(['', ';'.join(s), '', '', '', 'summary'])
        self.f.close()
        self.f = None
        self.w = None
