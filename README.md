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
- **Co-authoring models:** Claude Sonnet 5 (via GitHub Copilot) — architecture, `.trk`
  format, `game.py`, on-device testing/tuning, and the `generate_track.py` bridge to
  `qwen3-coder`. Claude Opus 5 (via Claude Code) — session 3's renderer rebuild. Per the
  course's
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

## Deploying to the N900

```
sh tools/deploy.sh                       # laptop -> /home/user/MyDocs/freracer
N900_HOST=root@10.0.0.71 sh tools/deploy.sh   # if DHCP moved it
```

`deploy.sh` copies only what Python 2.5 on the device actually runs — the game, the
tracks, and `tools/racer_fps.py`. The Python 3 tools (`generate_track.py`, which talks
to `sld-cloud`, and `render_shot.py`/`fake_pygame.py`, the off-device renderer) stay on
the laptop. It copies and stops; it never launches anything on the device.

It passes the N900's legacy SSH crypto options to `scp` directly rather than going
through the `n900` shim, which wraps `ssh` only — those options don't propagate through
a `ProxyCommand`. The laptop's OpenSSL 3.5 refuses the device's `ssh-rsa`/KEX/cipher
suite outright ("error in libcrypto") without them.

## Running it on the N900

From the Hildon desktop, tap the freracer icon (see "Launching from the Maemo desktop"
below). From a shell:

```
n900
cd /home/user/MyDocs/freracer
export DISPLAY=:0
python2.5 test_track.py                              # PASS: tracks/001-autumn-hills.trk
python2.5 game.py tracks/001-autumn-hills.trk         # real accelerometer, no time limit
python2.5 game.py                                    # same, but picks the lowest-numbered track in tracks/
```

A race ends with a result panel — time, par, hits — which stays up for 12 seconds or
until you tap. Before that existed, finishing returned straight out of `main()`, the
launcher's shell exited with it, and the player landed back at the app grid with no
explanation; the first playtest of the fixed renderer reported that as a crash.

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
`freracer.log`), and a 64×64 icon. This is a **one-time** step, separate from
`deploy.sh`: it runs on the device, as root, after the repo is there, and only needs
re-running if something in `desktop/` changes. It is already installed on the device.

```
n900 'sh /home/user/MyDocs/freracer/desktop/install.sh'
```

freracer then shows up under Games in the app grid like any other installed game — no
terminal required to play. This is a from-source install (`install(1)` copying three
files into place), not a `.deb`/Application Manager package; that would be the natural
next step if freracer needs to be distributed beyond this repo.

### Checking render performance first

The scanline road renderer draws up to `DRAW_DISTANCE` road bands per frame — the one
number most likely to need tuning for a 600 MHz CPU, the way fremarble's marble physics
constants were tuned from `tools/marble_fps.py` numbers instead of guessed.

```
python2.5 tools/racer_fps.py 15 120 3   # seconds, draw_distance, min_band_height
```

**The renderer is bound by pygame draw calls per frame, not by pixels.** This is the
single most useful thing to know before optimising it, and it is counter-intuitive
enough that it was got wrong once already: splitting the ground fill and the rumble
strip into left/right halves saved roughly 440k pixels a frame and cost 98 extra draw
calls, and measured **22.0 → 18.5 fps**. Fewer, bigger primitives win. A draw call
costs on the order of 90 µs here.

So `MIN_BAND_HEIGHT`, not `DRAW_DISTANCE`, is the frame-rate dial — it controls how many
bands earn their own calls without shortening the road. Measured on the device
(`001-autumn-hills`, sustained motion):

| | fps (avg / worst second) |
|---|---|
| `DRAW_DISTANCE=120`, `MIN_BAND_HEIGHT=1` | 22.0 / 20.7 |
| `DRAW_DISTANCE=120`, `MIN_BAND_HEIGHT=2` | 24.5 / 23.9 |
| **`DRAW_DISTANCE=120`, `MIN_BAND_HEIGHT=3`** (shipping) | **26.9 / 25.5** |
| `DRAW_DISTANCE=120`, `MIN_BAND_HEIGHT=4` | 27.6 / 27.1 |
| `DRAW_DISTANCE=100`, `MIN_BAND_HEIGHT=3` | 27.7 / 27.1 |
| `DRAW_DISTANCE=80`, `MIN_BAND_HEIGHT=3` | 29.5 / 28.8 |

`DRAW_DISTANCE` stays at 120 because it buys lookahead — 120 segments is two seconds of
road at `MAX_SPEED`, which is what makes a corner readable — and dropping it to 100 is
worth only 1.3 fps. The full game loop runs slower than the render probe: **~22 fps**
bot-driven, the difference being physics, sprites and telemetry.

Don't raise `MIN_BAND_HEIGHT` much past 3 without driving it. It quantises *which*
segments get drawn, so the choice changes as the camera moves, and a coarse threshold
can make the road stripes pop — which no still frame will show you.

The old numbers (`160 → 36 fps`, `120 → ~50 fps`) are void: they were measured against a
renderer that was discarding every road band but one, so they timed projection
arithmetic with almost no rasterisation behind it.

### Looking at a frame without the device

The N900 is the only machine in the project with pygame on it, which is how a renderer
that drew one band per frame survived two sessions of colour tuning. `render_shot.py`
runs `game.py`'s draw path against a software rasteriser (`tools/fake_pygame.py`) and
writes PNGs, so "does this frame look right" is answerable from the laptop:

```
python3 tools/render_shot.py tracks/001-autumn-hills.trk --frames 6 --out /tmp/shots
python3 tools/render_shot.py tracks/002-night-circuit.trk --at 4000 --offset -400
```

It renders correctness, not speed — it says nothing about frame rate, and nothing about
how the colours read on a resistive LCD outdoors. Both of those still need the device.

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
| `tools/render_shot.py`, `tools/fake_pygame.py` | render frames to PNG off-device, to check a rendering change before carrying it over |
| `tools/deploy.sh` | copy the game, tracks and `racer_fps.py` to the device over `scp` |
| `tools/generate_track.py` | prompts `qwen3-coder` on `sld-cloud` for new tracks, validates output |
| `desktop/` | Hildon app-grid launcher: `.desktop` entry, `/usr/bin/freracer` script, icon, `install.sh` |
| `.github/copilot-instructions.md` | the Python 2.5 bootstrap every model gets |

## Known behaviour / open questions

- **The road was never being drawn at all** (found and fixed 2026-09-07, session 3).
  Two independent bugs, either of which alone hides the road:
  1. `draw_road` walked its segments far-to-near — the correct painter's order — while
     keeping the near-to-far occlusion clip from the pseudo-3D renderer it was ported
     from. That clip compares a band's far edge against the previous band's near edge,
     but consecutive segments *share* that point: same segment dict, same z, so the same
     float. `y2 >= max_y` was therefore true by equality on the second iteration and
     every band nearer than the first was discarded. Exactly one band was drawn per
     frame, 0.1px tall, at the horizon. Everything that looked like road surface was the
     flat ground rectangle in the background surface — which is why two sessions of
     tuning `ROAD_COLOR` changed nothing: that colour had never been on screen.
  2. `track.py` integrates `curve` twice to bake an absolute centreline x into every
     segment, so a long bend is constant angular *acceleration*: by segment 330 of
     Autumn Hills the centreline is 22320 world units from the origin and pointing tens
     of degrees off `+z`. `draw_road` set `cam_x = player_x` — an offset the physics
     clamps to ±3 road widths — so on anything but the opening straight the camera was
     aimed at empty space. The renderer now re-accumulates the centreline offset from
     `curve` each frame starting at the camera, which is the standard treatment and
     amounts to aiming the camera down the road's own tangent.

  The same absolute-vs-relative confusion was in the collision tests, which added a
  segment's absolute centreline x to an obstacle and compared it against a
  centreline-relative `player_x`; both now compare in centreline-relative space.
- **What the renderer draws now**: per-band full-width ground stripes (the periphery
  motion cue — previously everything outside a narrow shoulder was one static colour),
  red/white rumble strips, dashed lane markers, roadside marker posts every 5 segments,
  and depth haze on all of it, pre-blended per distance at startup by `build_palette` so
  the frame loop only indexes a list. Obstacle and traffic sprites take the same haze and
  are drawn far-to-near.
- **Physics constants are still starting points**, and none of the graphics work has been
  seen on the device yet — it was verified by rendering frames through a software
  rasteriser off-device. `MAX_SPEED`, `STEER_GAIN` and `CENTRIFUGAL` are not yet tuned
  from a human play-test, and `DRAW_DISTANCE` needs a fresh `racer_fps.py` measurement
  (see above).
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
