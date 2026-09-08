# rng.py - the one random number generator freracer is allowed to use.
# Python 2.5 safe, and produces the same stream on Python 3.
#
# Everything procedural in freracer - the horizon backdrop, the journey's
# region chain, every chunk of road - has to come out identical on the
# device's Python 2.5.4 and on the laptop's Python 3, or the laptop cannot
# be used to test what the device will draw. `random` does not promise that
# (randrange changed in 3.2), so this is a tiny LCG on plain integers. It is
# not a good generator; it is a *stable* one, and it is fast enough.


class Rng(object):
    """Deterministic LCG. Rng(seed).pick(lo, hi) -> int in [lo, hi)."""

    def __init__(self, seed):
        self.s = int(seed) % 2147483648

    def pick(self, lo, hi):
        """Integer in [lo, hi). hi <= lo returns lo."""
        self.s = (1103515245 * self.s + 12345) % 2147483648
        if hi <= lo:
            return lo
        # The low bits of an LCG cycle quickly; use the high ones.
        return lo + (self.s >> 8) % (hi - lo)

    def uniform(self, lo, hi):
        """Float in [lo, hi), 1/10000 resolution."""
        return lo + (hi - lo) * (self.pick(0, 10000) / 10000.0)

    def sign(self):
        if self.pick(0, 2):
            return 1.0
        return -1.0

    def weighted(self, items):
        """items: sequence of (value, weight) with integer weights >= 0.

        Returns a value, or None if every weight is zero. Weights are
        integers on purpose: the stream is integer-only, so a weight table
        rounds the same way everywhere.
        """
        total = 0
        i = 0
        while i < len(items):
            total += items[i][1]
            i += 1
        if total <= 0:
            return None
        r = self.pick(0, total)
        i = 0
        while i < len(items):
            r -= items[i][1]
            if r < 0:
                return items[i][0]
            i += 1
        return items[-1][0]


def lattice(seed, i):
    """Value noise support: a stable float in [-1, 1] for lattice point i."""
    r = Rng(int(seed) * 7919 + int(i) * 104729 + 1)
    r.pick(0, 2)                    # one warm-up step: adjacent seeds start too alike
    return r.pick(0, 20001) / 10000.0 - 1.0


def noise(seed, x):
    """1-D value noise: smoothstep between lattice points at integer x."""
    i = int(x)
    if x < 0 and i != x:
        i -= 1
    f = x - i
    t = f * f * (3.0 - 2.0 * f)
    a = lattice(seed, i)
    b = lattice(seed, i + 1)
    return a + (b - a) * t
