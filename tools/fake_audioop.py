# fake_audioop.py - the five audioop calls synth.py uses, on numpy, for the
# laptop's Python 3.13+ where the audioop module no longer exists. Python 2.5
# on the device has the real one and never imports this. Installed into
# sys.modules['audioop'] by tools/render_song.py before synth is imported.
#
# Behaviour matches CPython's audioop for 16-bit mono input: add and mul clip
# to int16 (checked on the device: 30000 + 10000 -> 32767, not a wrap), and
# ratecv is a linear interpolator.
import numpy as np

_I16 = np.dtype('<i2')


def _arr(frag):
    return np.frombuffer(frag, dtype=_I16)


def _clip(a):
    return np.clip(np.rint(a), -32768, 32767).astype(_I16).tobytes()


def add(f1, f2, width):
    if width != 2:
        raise ValueError('fake_audioop: width 2 only')
    if len(f1) != len(f2):
        raise ValueError('fake_audioop.add: lengths differ')
    return _clip(_arr(f1).astype(np.int64) + _arr(f2).astype(np.int64))


def mul(frag, width, factor):
    return _clip(_arr(frag).astype(np.float64) * factor)


def tostereo(frag, width, lfactor, rfactor):
    a = _arr(frag).astype(np.float64)
    out = np.empty(len(a) * 2, dtype=np.float64)
    out[0::2] = a * lfactor
    out[1::2] = a * rfactor
    return _clip(out)


def max(frag, width):
    a = _arr(frag)
    if len(a) == 0:
        return 0
    return int(np.abs(a.astype(np.int64)).max())


def ratecv(frag, width, nchannels, inrate, outrate, state, weightA=1, weightB=0):
    if nchannels != 1 or width != 2:
        raise ValueError('fake_audioop.ratecv: mono 16-bit only')
    a = _arr(frag).astype(np.float64)
    n_in = len(a)
    n_out = int(n_in * outrate / float(inrate))
    if n_in == 0 or n_out == 0:
        return (''.encode('latin-1'), None)
    x = np.arange(n_out) * (inrate / float(outrate))
    y = np.interp(x, np.arange(n_in), a)
    return (_clip(y), None)
