# generate_track.py -- ask a model on sld-cloud (Ollama) to design a freracer .trk
# track, then validate the result locally before it ever reaches the device.
#
# This is NOT run on the N900. It runs anywhere with network access to sld-cloud
# (this laptop, over the existing `ssh sld-cloud` shortcut) and Python 3 + requests,
# or plain urllib if requests is unavailable. It writes a candidate .trk file; a
# human (or the directing assistant, by hand) copies validated tracks onto the
# device with scp over the `n900` shortcut, per the project's "bytes to atoms" rule.
#
#   python3 tools/generate_track.py --theme dusk-city --name "Night Circuit" \
#       --out tracks/002-night-circuit.trk
#
# Talks to Ollama's HTTP API. By default assumes an SSH tunnel or direct reachability
# to sld-cloud:11434; pass --host to override (e.g. after `ssh -L 11434:localhost:11434
# sld-cloud`, or run this script *on* sld-cloud itself).
import argparse
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import track  # noqa: E402  (the game's own loader/validator, Python 2.5-safe module)

MODEL = 'qwen3-coder:30b-a3b-q4_K_M'
DEFAULT_HOST = 'http://127.0.0.1:11434'

FORMAT_DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'tracks', 'FORMAT.md')

VOCAB = """
Racing-course vocabulary you can draw on (Pole Position / OutRun / Ridge Racer / Gran
Turismo tradition): long straight, sweeping right-hander, sweeping left-hander, tight
hairpin, chicane (quick left-right or right-left), climb, crest, descent, banked corner
feel (approximate with curve + hill together), esses (alternating S-bends), a scenic
straight for a photo-mode moment, a braking zone before a hairpin (a straight with no
curve right before a high-curve ROAD stretch).
"""

SYSTEM_PROMPT = """You design race tracks for a small 2D pseudo-3D racing game as plain
text files in a specific format. Output ONLY the track file contents: no markdown code
fences, no explanation, no commentary before or after. Follow the format exactly."""


def build_prompt(name, theme, seed, difficulty):
    fmt = open(FORMAT_DOC, 'r').read()
    return (
        SYSTEM_PROMPT + "\n\n" + fmt + "\n\n" + VOCAB + "\n\n" +
        "Design a track named \"%s\" with THEME %s and SEED %d, difficulty: %s. " % (
            name, theme, seed, difficulty) +
        "Aim for 300-700 total segments across all ROAD lines, a PAR time you estimate "
        "for a skilled player, 3-8 OBSTACLE lines and 2-5 TRAFFIC lines placed on "
        "straights and gentle curves (not inside tight hairpins). Keep curve values "
        "roughly in -6..6 and hill changes roughly in -500..500 per ROAD line so the "
        "road stays smooth. Output only the track file."
    )


def call_ollama(host, prompt):
    body = json.dumps({
        'model': MODEL,
        'prompt': prompt,
        'stream': False,
        'options': {'num_ctx': 8192},
    }).encode('utf-8')
    req = urllib.request.Request(
        host.rstrip('/') + '/api/generate', data=body,
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=900) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    return data.get('response', '')


def strip_fences(text):
    text = text.strip()
    text = re.sub(r'^```[a-zA-Z]*\n', '', text)
    text = re.sub(r'\n```$', '', text)
    return text.strip() + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', default='Generated Track')
    ap.add_argument('--theme', default='autumn-hills',
                     choices=['autumn-hills', 'dusk-city', 'coast'])
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--difficulty', default='medium',
                     choices=['easy', 'medium', 'hard'])
    ap.add_argument('--host', default=DEFAULT_HOST)
    ap.add_argument('--out', required=True)
    ap.add_argument('--max-attempts', type=int, default=3)
    args = ap.parse_args()

    prompt = build_prompt(args.name, args.theme, args.seed, args.difficulty)

    attempt = 1
    while attempt <= args.max_attempts:
        sys.stderr.write('attempt %d: asking %s ...\n' % (attempt, MODEL))
        raw = call_ollama(args.host, prompt)
        candidate = strip_fences(raw)

        tmp_path = args.out + '.candidate'
        f = open(tmp_path, 'w')
        try:
            f.write(candidate)
        finally:
            f.close()

        trk = track.load(tmp_path)
        errors = track.validate(trk)
        if not errors:
            os.rename(tmp_path, args.out)
            sys.stdout.write('PASS: %s (%s, %d segments, lap %.0f units, par %gs)\n' % (
                args.out, trk['name'], len(trk['segments']), trk['lap_length'], trk['par']))
            return 0

        sys.stderr.write('attempt %d FAILED validation:\n' % attempt)
        for e in errors:
            sys.stderr.write('  - %s\n' % e)
        os.remove(tmp_path)
        attempt += 1

    sys.stderr.write('gave up after %d attempts; no valid track written\n' % args.max_attempts)
    return 1


if __name__ == '__main__':
    sys.exit(main())
