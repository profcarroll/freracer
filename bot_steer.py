import sys
import time

def parse_script(script):
    parts = script.split(';')
    out = []
    i = 0
    while i < len(parts):
        part = parts[i].strip()
        if part:
            xyz, secs = part.split(':', 1)
            x, y, z = xyz.split(',', 2)
            out.append((int(x), int(y), int(z), float(secs)))
        i += 1
    return out

def write_tilt(path, x, y, z):
    f = open(path, 'w')
    try:
        f.write('%d %d %d\n' % (x, y, z))
        f.flush()
    finally:
        f.close()

def main():
    if len(sys.argv) < 3:
        sys.stderr.write('usage: python2.5 bot_steer.py <tilt_file> <script>\n')
        return 2
    path = sys.argv[1]
    script = parse_script(sys.argv[2])
    i = 0
    while i < len(script):
        x, y, z, secs = script[i]
        end = time.time() + secs
        while time.time() < end:
            write_tilt(path, x, y, z)
            time.sleep(0.1)
        i += 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
