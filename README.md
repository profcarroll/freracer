# freracer

A pseudo-3D scanline racer for the **Nokia N900** (Maemo 5 "fremantle", 2009), in the
tradition of Pole Position, OutRun, Ridge Racer and Gran Turismo, whose courses are
designed by a self-hosted language model. Sibling project to
[`fremarble`](https://github.com/profcarroll/fremarble); same device, same course
(PSAM 5600 B, *Small Linux Devices, Large Language Models*, Parsons, Fall 2026), same
"bytes to atoms" rule.

- **Device:** Nokia N900, 600 MHz Cortex-A8, 245 MB RAM, 800×480 resistive touch, 3-axis
  accelerometer, vibrator. Python 2.5.4 + pygame 1.9.1.
- **Steering:** the accelerometer, tilt left/right. No touchscreen driving controls —
  throttle is automatic (arcade cabinet style: you are always accelerating toward top
  speed unless you're off the road). Curbs, obstacles and other traffic buzz the
  vibrator on contact.
- **Courses:** built from a short, human-describable vocabulary — straights, sweepers,
  hairpins, climbs, descents — not raw per-pixel geometry, so a model can design one
  without producing kinked, unplayable road. See `tracks/FORMAT.md`.
- **Course designer:** `qwen3-coder:30b-a3b-q4_K_M` on the same free Oracle Ampere A1
  node (`sld-cloud`) used by fremarble. `tools/generate_track.py` prompts it, then
  validates the result with the game's own loader before anything is written.
- **Co-authoring model:** Claude Sonnet 5 (via GitHub Copilot) — architecture, `.trk`
  format, `game.py`, on-device testing/tuning, and the `generate_track.py` bridge to
  `qwen3-coder`. Per the course's
  [ATTRIBUTION.md](https://github.com/mfadt/sld-fall-2026/blob/main/ATTRIBUTION.md),
  every commit trailer names it.
- **Status:** prototype plays on the device. One hand-built track (Autumn Hills, a Gran
  Turismo-flavoured seasonal opener) and one model-generated track (Night Circuit,
  `qwen3-coder`, passed validation on the first attempt). No human has driven it with
  the accelerometer yet — see `HANDOFF.md`.

## The idea

Same research question as fremarble, different genre: can a model on a cloud node design
game content for a device it will never run on, well enough that the device's own sensor
and player make it worth playing? Racing adds two things marble-tilt didn't have: a
forward dimension (speed, braking zones, racing lines) and other agents on the track
(traffic to read and react to, not just static hazards).

## Running it on the N900

From the Hildon desktop, tap the freracer icon (see "Launching from the Maemo desktop"
below). From a shell:

```
scp -r . root@<n900-ip>:/home/user/MyDocs/freracer
ssh root@<n900-ip>
cd /home/user/MyDocs/freracer
export DISPLAY=:0
python2.5 test_track.py                              # PASS: tracks/001-autumn-hills.trk
python2.5 game.py tracks/001-autumn-hills.trk         # real accelerometer, no time limit
python2.5 game.py                                    # same, but picks the lowest-numbered track in tracks/
```

`game.py [track] [tilt_source] [telemetry_csv] [timeout_s]` — all arguments are optional.
With no track given it plays the lowest-numbered `.trk` in `tracks/` (this is what the
desktop launcher does). Hold the device the way you want to play for the first
half-second: that angle becomes "straight ahead". Reach the finish line or touch the
screen to end; there is no time limit for human play (the 4th, `timeout_s`, argument is
only for scripted bot runs that might otherwise never reach the finish line — see below).
The last line printed is always
`RESULT outcome=... elapsed=... hits=... par=... frames=... avg_fps=...`.

### Launching from the Maemo desktop

`desktop/` holds a real Hildon app-grid entry: `freracer.desktop`, a `/usr/bin/freracer`
launcher script (cds into the install directory, runs untimed, logs to
`freracer.log`), and a 64×64 icon. Install once, as root, after the repo is on the
device at `/home/user/MyDocs/freracer`:

```
ssh root@<n900-ip> 'sh /home/user/MyDocs/freracer/desktop/install.sh'
```

freracer then shows up under Games in the app grid like any other installed game — no
terminal required to play. This is a from-source install (`install(1)` copying three
files into place), not a `.deb`/Application Manager package; that would be the natural
next step if freracer needs to be distributed beyond this repo.

### Checking render performance first

The scanline road renderer draws up to `DRAW_DISTANCE` road bands per frame — the one
number most likely to need tuning for a 600 MHz CPU, the way fremarble's marble physics
constants were tuned from `tools/marble_fps.py` numbers instead of guessed. Measured on
the actual device with `tools/racer_fps.py`: `DRAW_DISTANCE=160` gave 36 avg / 19 worst
fps (rough, uneven), `120` gave ~50 avg / ~49 worst fps (smooth). `track.py` and
`game.py` now default to 120. Re-run this if the road, sprite count, or theme changes
enough to matter:

```
python2.5 tools/racer_fps.py 15 120   # seconds, draw_distance
```

### Playing it with a bot

Tilt is read every frame from one file, exactly like fremarble:

```
echo "0 0 -1000" > /tmp/tilt
python2.5 game.py tracks/001-autumn-hills.trk /tmp/tilt telemetry/bot.csv 30 &
python2.5 bot_steer.py /tmp/tilt "0,300,-800:2;0,-300,-800:2;0,0,-1000:2"
```

Each script segment is `x,y,z:seconds` in milli-g, rewritten every 100 ms (`y` is the
steering axis, same convention as fremarble's marble control).

## Designing a new track

```
ssh -L 11434:127.0.0.1:11434 sld-cloud   # or run generate_track.py on sld-cloud directly
python3 tools/generate_track.py --name "Night Circuit" --theme dusk-city \
    --seed 2 --difficulty medium --out tracks/002-night-circuit.trk
```

`generate_track.py` builds a prompt from `tracks/FORMAT.md` plus a short racing-course
vocabulary, asks `qwen3-coder`, strips any stray code fences, and validates the result
with `track.py` — retrying (default 3 attempts) until a track passes or attempts run
out. Only a validated `.trk` file is ever written; nothing is copied to the device by
this tool (bytes to atoms — a human carries it over with `scp`).

## Files

| Path | What |
|---|---|
| `game.py` | game loop, pseudo-3D road renderer, physics, steering, haptics |
| `track.py`, `test_track.py`, `tracks/FORMAT.md` | `.trk` format, loader/builder, validator |
| `tracks/001-autumn-hills.trk` | the first, hand-built track |
| `telemetry.py` | 10 Hz CSV writer (z, speed, lateral offset, tilt, event) |
| `bot_steer.py` | scripted tilt writer, same convention as fremarble's `bot_tilt.py` |
| `tools/racer_fps.py` | frame-rate probe for the road renderer, run on-device first |
| `tools/generate_track.py` | prompts `qwen3-coder` on `sld-cloud` for new tracks, validates output |
| `desktop/` | Hildon app-grid launcher: `.desktop` entry, `/usr/bin/freracer` script, icon, `install.sh` |
| `.github/copilot-instructions.md` | the Python 2.5 bootstrap every model gets |

## Known behaviour / open questions

- **First playtest (2026-09-07) found the game was not really playable**: steering used
  fremarble's `raw_y` axis, which barely moves when the phone is held landscape for a
  racer; the road was flat, low-contrast, and had no roadside detail, so it was hard to
  tell where you were on it; and the vibrator sysfs path is root-only, so haptics never
  actually fired when launched as `user` from the desktop. All three are now fixed (see
  the corresponding commit and `game.py` comments): steering reads `raw_x`, measured live
  on-device by rolling the phone and watching which axis actually moved; haptics go
  through MCE's `req_vibrator_pattern_activate` D-Bus call instead of the sysfs file;
  and `draw_road` now draws a banded, alternating-colour shoulder plus roadside marker
  poles every 5 segments, on top of higher-contrast road paint. **Still needs a real
  human playtest** to confirm it feels right - only bot-driven and render-only tests
  have run so far.
- **Physics constants are still starting points.** `DRAW_DISTANCE` (120) is tuned from
  real `tools/racer_fps.py` numbers; with the new shoulder/pole rendering the full game
  loop runs ~35-43 fps under sustained off-road bot steering (vs ~49 fps for bare-road
  rendering in isolation) - stable, but re-run `racer_fps.py` and reconsider
  `DRAW_DISTANCE` if more roadside detail is added. `MAX_SPEED`, `STEER_GAIN` and
  `CENTRIFUGAL` are not yet tuned from a human play-test.
- **Traffic loops the lap on a timer, not a queue**: each `TRAFFIC` car's position is a
  pure function of race time and lap length, so it's always somewhere on the ribbon, but
  it does not react to the player or to other traffic.
- **No collision cooldown tuning yet**: obstacles hit once and stay disabled for the run;
  traffic has a flat 2 s cooldown after a hit. Untested for feel.
- **Haptics are debounced, not continuous**: curb/grass buzz at most every 0.35 s while
  sustained (an early version buzzed every frame, which meant forking a `dbus-send`
  process per frame and cut fps from ~49 to ~18 in testing) - hits are already one-shot
  per obstacle/traffic car so they didn't need debouncing.

## License

MIT, matching fremarble and the course's own materials.
