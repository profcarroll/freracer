# Handoff — end of session 5 (the soundtrack)

For the next session, whoever holds the keyboard: a person or an assistant.

## Session 5: the road has a soundtrack

`docs/SOUNDTRACK.md` is the record: what the N900 can do with sound from Python 2.5,
measured on the device, and the procedural synthesizer built on it (`synth.py`,
`music.py`, `tools/render_song.py`, `--music` on `racer_fps.py`, `--mute` on `game.py`).
It is on the `soundtrack` branch, deployed to the device, bot-driven there, and has
**not been listened to on the device's speakers by a person** — every level was set
from WAVs rendered on the laptop.

The three things worth knowing before touching it:

1. **PulseAudio, not the synth, is the cost.** Nokia's system-mode pulse takes about a
   third of the CPU whenever any stream plays anything; sample rate, channel count and
   mono/stereo make no difference, only the SDL buffer size does, and 4096 is the knee.
   The full game loop measures ~21 fps with music, ~26 muted, on the journey. There is
   no cheaper sink to route to (pulse owns `hw:0,0`; everything that is not the phone
   stack is class `x-maemo` and goes through the music chain).
2. **`pygame.mixer.Sound(<str>)` leaves a stale TypeError** that surfaces at the next
   unrelated C call (`audioop.ratecv`, twice). Sounds are built from a WAV in a
   `cStringIO`. Two probes were misread because of this before it was found.
3. **Timing is sample-accurate, not frame-locked.** Beats are rendered as generators a
   few ms per frame and handed to one channel with `Channel.queue()`, which SDL_mixer
   1.2.6 swaps gaplessly. The composer is therefore fed the road 1.2 s ahead of the car
   (`music.road_context`), and 3 s ahead for corner build-ups.

What session 6 should do, in order:

1. `n900 'cd /home/user/MyDocs/freracer && DISPLAY=:0 python2.5 music.py 20 1 farmland,mountains'`
   and listen. Then drive a journey from the icon with the sound on. Write down whether
   the hats and the lead read on the small speakers, whether 21 fps feels worse than 26,
   and whether the corner roll arrives before the corner.
2. Tune `STYLES` in `music.py` from that: tempo, density, instruments. Regenerate the
   WAVs with `render_song.py` to compare; the seed replays.
3. Decide whether the music is worth the frame rate by default, or whether the launcher
   should pass `--mute`. Headphones or the FM transmitter may skip the speaker
   protection stage of pulse's chain and cost less; untested.
4. Open items in `docs/SOUNDTRACK.md` §5: traffic is silent, `.trk` tracks have no
   motif tags so no corner rolls, styles could become a text format the model writes.

## Session 4 handoff, still current below

### Session 4: the road no longer ends

`docs/INFINITE-ROAD-SPEC.md` Phase 1 is built and passes its offline tests. It was
deployed and driven on the device once: 7.0 miles to the end card, no traceback
(PR #2). No tuning notes were taken from that drive yet. Phase 0 of the spec (measure fps on the device with the
session 3 renderer, then a human drive of Autumn Hills, then write down what a `curve`
of 3 and 6 feel like) was skipped at the user's direction, so every curve range in
`regions.py` is still the spec's provisional guess.

What exists:

- `rng.py` — `game._Rng` moved out so `track.py`, the generator and the laptop tools
  share one stable stream. It now uses the LCG's high bits (`s >> 8`): the low bit of
  a mod-2^31 LCG alternates 0,1,0,1, which made `pick(0, 2)` useless as a coin. The
  procedural backdrops therefore differ slightly from session 3's; nothing else does.
- `regions.py` — data only: farmland, foothills, mountains (width, straight length,
  curve, hill amplitude, altitude band, motif weights, dwell, obstacles, palette), plus
  the full 11-region successor table from spec §4.2 so it need not be rewritten as
  regions are added. Unbuilt successors collapse onto farmland (`STAND_IN`); that rule
  disappears by itself as regions get built.
- `journey.py` — `Generator(seed)`: region chain (dwell limits, no-immediate-return,
  recent-visit halving, opener set), parametric motif recipes from spec §4.6, value-
  noise terrain biased toward each region's altitude band, per-region obstacles on
  straights only, static validation with reroll. A transition is a 150-segment straight
  that ramps the width; palette blending is Phase 2. Chunk plans are ~40 µs each.
- `window.py` — the segment window: `feed()` expands *one stretch per frame* (a chunk
  is planned in one go, expanded lazily) so generation cost is spread; `trim()` drops
  road 20 segments behind in batches of 40. A finite `.trk` is wrapped in the same
  structure, so `draw_road` has one path.
- `track.py` — `expand_stretch` is the shared expander; segments carry `heading` (the
  running sum of curve, what the backdrop pans by) and `region`, and no absolute `x`.
  `WIDTH` between `ROAD` lines now ramps the next stretch (see `tracks/FORMAT.md`).
  `validate` also rejects width steps.
- `game.py` — `--journey [seed]`, per-region palettes/sky/backdrop picked per band and
  per frame (hard switch, zero extra draw calls), odometer HUD (one blit, re-rendered
  every tenth of a mile), journey result panel, `RESULT` gains `seed= distance=
  regions=`, journey stop is `outcome=stop`. Events: `region-<name>`, `starve`.
- `test_journey.py` (500 seeds × 300 chunks, 4 s on the laptop), `tools/journey_dump.py`,
  `tools/journey_export.py`, `tools/render_shot.py --journey`, `tools/racer_fps.py
  --journey`. `tools/fake_pygame.py` gained enough of `font`/`time`/`event.clear` for
  the *whole* `game.main()` loop to run off-device; both modes were run that way for
  20 s and 130 s with no traceback, zero starves, and region changes logged.
- `desktop/freracer` passes `--journey`. **Re-run `desktop/install.sh` on the device.**

Phase 1's exit criterion is a human drive: ten minutes with no starvation and no
visible kink, and someone saying the terrain "changes". The first drive happened;
the notes from it (what a mountain hairpin feels like, whether the regions read)
have not been written down. What session 5 should do, in order:

1. `sh tools/deploy.sh`, then on the device `python2.5 test_journey.py --quick` (the
   Python 2.5 side of the determinism claim has only been reasoned about, not run),
   `python2.5 tools/racer_fps.py 15 120` for the session 3 baseline the spec's Phase 0
   asked for, then `python2.5 tools/racer_fps.py 60 --journey 4471`. The journey number
   includes generation and must show `starves=0`; if the worst second is well under the
   probe's, the per-frame budget in `window.feed` is the first suspect.
2. `n900 'sh /home/user/MyDocs/freracer/desktop/install.sh'`, then drive from the icon.
3. Retune `regions.py` from that drive. Mountains use the spec's hairpin (`curve` 5–6
   for 30 segments); nobody knows yet whether that is a corner or a wall.

## Session 3 handoff, still current below

**Bottom line: the road was never being drawn, and now it is.** Sessions 1 and 2 tuned
`ROAD_COLOR` twice against a renderer that discarded 119 of its 120 road bands every
frame; what looked like a badly coloured road surface was the flat ground rectangle in
the background surface. Session 3 found that, found a second bug that put the camera
kilometres away from the road on every curve, fixed both, and rebuilt the visual
language on top (depth haze, scrolling full-width ground, a panning horizon). **None of
it has been seen on the device.** It was verified by rendering frames through a software
rasteriser off-device — which is a much stronger check than the previous sessions had,
but it is not a screen, and it says nothing at all about frame rate.

Still true from session 2: **no human has driven the corrected build.** Don't trust any
of `MAX_SPEED` / `STEER_GAIN` / `CENTRIFUGAL` / `DRAW_DISTANCE` until someone does — and
`DRAW_DISTANCE`'s measured basis is now void, see below.

## Where things are

| Thing | Where |
|---|---|
| This repo | `github.com/profcarroll/freracer` (private) |
| Working copy on the device | `/home/user/MyDocs/freracer/` on the N900 |
| N900 access | laptop shortcut `n900` (root over legacy SSH crypto, same shim as fremarble). IP 10.0.0.70 by DHCP. |
| Desktop launcher | installed (`desktop/install.sh`); freracer appears in the Hildon app grid under Games |
| Cloud node | `ssh sld-cloud`. Ollama on 127.0.0.1:11434. `qwen3-coder:30b-a3b-q4_K_M` is the
  track designer — reach it from the laptop with `ssh -L 11434:127.0.0.1:11434 sld-cloud`. |
| Sibling project | `fremarble` — same device, same course, same conventions. |
| Device clock | fixed by the user this session (was stuck around a 2009 epoch date; telemetry filenames from before the fix are dated accordingly and harmless to ignore) |

## The rule

**Bytes to atoms.** Assistants produce text. Nothing runs on the device until a person (or the
directing assistant, by hand, over SSH) has read it and carried it there. (This session,
as in session 1, the user explicitly authorized the assistant to SSH into the device
directly — see `.github/copilot-instructions.md`.)

## Session 1 recap (see git log for full detail)

Scaffolded the whole project from fremarble's conventions (`.trk` format, `track.py`,
`telemetry.py`, `bot_steer.py`), built the pseudo-3D renderer and game loop, tuned
`DRAW_DISTANCE=120` from real on-device fps measurements (50 avg/49 worst), fixed two
bugs found by bot-only testing (grass-penalty ordering, unbounded lateral drift), and
generated a second AI track (`tracks/002-night-circuit.trk`) via `qwen3-coder` on
`sld-cloud`. Added a Hildon desktop launcher (`desktop/`) so freracer runs from the app
grid, not just a shell — that surfaced two more real bugs (see below), because it's the
first time the game ran as the unprivileged `user` account instead of over an interactive
root SSH session.

## Session 2: first human playtest, four real bugs found and fixed

The user actually picked up the device and drove. Findings, in the order they were found
and fixed:

1. **Steering did nothing noticeable.** Session 1 copied fremarble's `raw_y` axis
   verbatim — correct for fremarble's flat-on-a-table tilt game, wrong for a racer held
   upright in landscape. Measured live: had the user roll the phone landscape while
   sampling `/sys/class/i2c-adapter/i2c-3/3-001d/coord` at 10 Hz from the laptop. Rolling
   left swung `raw_x` from ~30 to ~650+ mg; `raw_y` stayed in its resting noise band.
   Fixed to read `raw_x`, sign chosen so roll-left steers left. **This still hasn't been
   felt by a human** — the axis fix was verified by instrumented sampling, not by someone
   actually steering with it, because the same playtest also hit bug 3 below before they
   got that far.
2. **Haptics never fired.** `/sys/class/leds/twl4030:vibrator/brightness` is
   root:root 0644; the desktop launcher runs the game as `user`, so every vibrator write
   silently failed (caught by a bare `except Exception: pass`). Fixed by switching to
   MCE's `req_vibrator_pattern_activate` D-Bus call (`com.nokia.mce`), which `user` can
   call directly — verified interactively over SSH first, before touching game code.
3. **Fixing #2 naively caused "freezes with rumbles and quits."** The first attempt
   called `dbus-send` via `subprocess.Popen` directly from the frame loop. Forking the
   whole pygame-loaded game process is expensive enough on 600 MHz ARM to stall the
   frame loop; sustained rumble-strip contact re-triggered that fork every 0.35 s,
   which is exactly what the user described. The `outcome=quit` results in the log
   confirm this wasn't a crash (no traceback ever appeared) — it's the touchscreen
   `MOUSEBUTTONDOWN`-ends-race handler firing, almost certainly because the user tapped
   the screen when it appeared frozen. Fixed with `buzz_helper.py`: one small, idle
   process spawned once before pygame/track surfaces grow the parent's memory; game.py
   now writes a pattern name to its stdin pipe instead of forking `dbus-send` itself, so
   the per-event fork happens in the small helper. Bot-verified stable ~37-43 fps under
   continuous rumble/grass contact, no stutter, no leftover processes.
4. **Road barely visible against the ground.** `dusk-city`'s grass, `(30,30,34)`, was
   almost the same dark neutral grey as the road paint; `autumn-hills`' olive green
   wasn't different enough in luminance either, especially outdoors on a low-contrast
   LCD. Road is now a firmly dark, neutral, low-saturation grey; every theme's ground
   colour was pushed toward a clearly different *hue* (amber/fall foliage, dusky purple,
   brighter green) rather than just a different shade of the same grey.

One genuinely good sign buried in the log from this session: after the earlier
frozen/quit attempts, one run completed a **full lap in 358 s (~6 min), avg 38 fps,
1 hit** — so a full drive is possible even with the pre-fix bugs. Nobody has confirmed
whether it's fun, or whether it's still readable/steerable, since the fixes above landed.

## Session 3: the road was never on screen

The user asked whether the Atari-2600 look was a hardware ceiling and whether 16-bit or
32-bit was reachable. It was not a ceiling: the renderer already implemented the
OutRun/Super-Scaler scanline algorithm, the panel is 16-bit, and the reason it looked
8-bit is that almost none of the renderer was running.

1. **`draw_road` drew exactly one band per frame, out of 120.** It walked far-to-near
   (the correct painter's order) while keeping the near-to-far occlusion clip from the
   pseudo-3D renderer it was ported from. That clip compares a band's far edge to the
   previous band's near edge — but consecutive segments *share* that point, same dict,
   same z, same float — so `y2 >= max_y` was true by equality on the second iteration
   and every nearer band was discarded. The one surviving band was 0.1px tall, 56px
   wide, on the horizon. Everything else on screen was `build_theme_background`'s flat
   ground rectangle. This is why two sessions of colour tuning did nothing: `ROAD_COLOR`
   had never been rendered.
2. **The camera was aimed at empty space on every curve.** `track.py` integrates `curve`
   twice to bake an absolute centreline x into each segment, so a long bend is constant
   angular *acceleration*: by segment 330 of Autumn Hills the centreline is 22320 units
   from the origin, heading tens of degrees off `+z`. `draw_road` used
   `cam_x = player_x`, which the physics clamps to ±3 road widths. Past the opening
   straight, the road was simply not in frame. The renderer now re-accumulates the
   centreline offset from `curve` each frame starting at the camera — the standard
   pseudo-3D treatment, equivalent to aiming the camera down the road's own tangent.
3. **Collisions had the same absolute-vs-relative confusion**: `player_x` was treated as
   centreline-relative by the off-road test and as an absolute world x by the hit tests,
   which added the segment's absolute centreline x to the obstacle. Both now compare in
   centreline-relative space.
4. **Visual language rebuilt on top**, all of it verified by rendering frames:
   per-band full-width ground stripes (Rect fills — the periphery motion cue; previously
   everything outside a narrow shoulder was one static colour), depth haze pre-blended
   per distance at startup by `build_palette` so the frame loop only indexes a list, a
   procedurally generated horizon backdrop that pans with the road's heading
   (`build_backdrop` — ridges for the outdoor themes, a lit skyline for `dusk-city`),
   fogged sprites drawn far-to-near, and higher-contrast stripe pairs for an outdoor LCD.

**32-bit is not reachable** and is not worth chasing: texture-mapped polygons, Gouraud
shading and alpha in pure Python 2.5 over SDL 1.2, with no GPU path pygame 1.9.1 can
use, is not a tuning problem. 16-bit Super Scaler is the right target and is what the
renderer now is.

### Measured on the device, at the end of session 3

The renderer is bound by **pygame draw calls per frame, not by pixels** — roughly 90 µs
a call, with the pixels behind them nearly free. This got assumed the wrong way round
once: splitting the ground fill and rumble strip into left/right halves flanking the
road saved ~440k pixels a frame, cost 98 draw calls, and measured 22.0 → 18.5 fps.
Reverted. Fewer, bigger primitives win here.

So `MIN_BAND_HEIGHT`, not `DRAW_DISTANCE`, is the frame-rate dial — it drops draw calls
without shortening the road. At `DRAW_DISTANCE=120`: 1 → 22.0 fps, 2 → 24.5, 3 → 26.5,
4 → 27.6. Shipping at 3, which measures **26.9 avg / 25.5 worst** on the render probe and
**~22–24 fps for the full game loop**. `DRAW_DISTANCE` stays at 120 for lookahead (two
seconds of road at `MAX_SPEED`); cutting it to 100 is worth only 1.3 fps.

Don't raise `MIN_BAND_HEIGHT` past 3 without driving it — it quantises which segments get
drawn, so the choice changes as the camera moves, and a coarse threshold can make the
stripes pop. No still frame will show that.

### The "crash" was the finish line

First human drive of the fixed build reported the game crashing once it got up to speed.
It wasn't crashing. `freracer.log` has never contained a traceback, and both runs ended
`outcome=finish`, under par, with no collisions — 12.1 s and 10.3 s against a par of 22.
The lap is 48000 units and `MAX_SPEED` is 6000/s, so a clean run is **eight seconds
long**. `main()` then returned, the launcher's shell exited with it, and the player was
dropped at the app grid with no explanation. `draw_result`/`hold_result` now show a
result panel (time, par, hits) for 12 s or until tapped.

**The course is far too short for the car.** Par of 22 s was written for a much slower
average speed than the game actually delivers. This is the next real design question:
either the tracks get much longer, or `MAX_SPEED` comes down, or both. See "next steps".

### Open: the grass is a full stop, not a penalty

`in_grass` applies `BRAKE_DECEL` (5200) unconditionally while `ACCEL` is 2400, so terminal
speed off-road is exactly zero — despite `OFFROAD_MAX_SPEED` (2700) plainly intending
"slower, still moving". Recovering means holding a tilt for ~7 s to crawl sideways back
onto the tarmac at the `STEER_MIN_SPEED_FRAC` floor before the throttle does anything. On
an arcade racer with no manual throttle, one clipped corner ends the run in practice.
Bot-confirmed twice (`telemetry/bot-s3.csv`, `bot-s4.csv`): speed 887 → 0 in under a
second of grass, then zero for the remaining 13 s.

The *value* of an off-road speed is a feel question and deliberately wasn't guessed at.
The *structure* isn't: a brake that exceeds acceleration has terminal velocity zero,
which no answer to "how slow should grass be" would ask for. Decelerate toward a named
grass cap instead of through it, then tune the cap by driving.

### What session 4 must measure first

`DRAW_DISTANCE`'s basis is gone. `160 → 36 fps` and `120 → ~50 fps` were measured
against the one-band renderer, so they measured projection arithmetic with essentially
no rasterisation behind it. The corrected renderer cuts projections per frame in half
(one per segment, since adjacent segments share an endpoint) and folds sub-pixel bands
together (~120 candidates → ~55 drawn, ~160 polygons and ~90 rect fills per frame), but
it is now genuinely filling pixels. It could land either side of the old number. Run
`python2.5 tools/racer_fps.py 15 120` on the device before anything else, then 90 and
70, and pick from the worst-second column.

## Next steps, in order — "a fresh approach"

The user asked for a fresh approach next session rather than more one-bug-at-a-time
patching. Suggested starting point:

0. **Measure fps on the device, then play it.** See "What session 4 must measure first"
   above — `DRAW_DISTANCE` is the one constant that can make everything else unreadable.
1. **Play it. Actually drive it, on the corrected build, before touching any more code.**
   Don't guess at `STEER_GAIN`/`CENTRIFUGAL`/`MAX_SPEED` — every constant in `game.py` is
   still session-1 guesswork that's never been felt by a human hand. If it's still not
   fun or not controllable, that telemetry (now that `raw_x` is the real steering signal)
   will actually mean something, unlike session 1's bot-only runs.
1.5. **Lap length / `MAX_SPEED` is now the biggest open question** — see "The 'crash'
   was the finish line" above. A course that ends in ten seconds cannot be judged for
   feel, because it is over before the player has settled into it.
2. **Consider instrumenting *before* re-tuning by feel.** e.g. log the actual `raw_x`
   range during a real drive (not a synthetic roll test) so `STEER_GAIN`/`TILT_DEAD_ZONE`
   are picked from real driving-grip data, not the one 22-second sample from this
   session's axis discovery.
3. **Track content is still untouched** and is now the sparsest thing left. The visual
   language was reworked in session 3, but both tracks (`001-autumn-hills.trk`
   hand-built, `002-night-circuit.trk` AI-generated) were authored against a renderer
   nobody could see, so nobody has ever judged whether their corners, crests and
   obstacle placement actually read. Worth re-evaluating now that they are visible —
   and note that a `curve` value means angular *acceleration*, so long high-`curve`
   stretches spiral much harder than their author probably intended.
4. **`CENTRIFUGAL` is still 0.0007**, flagged in session 1 as too weak to require
   cornering — not yet revisited this session because bigger bugs (steering axis,
   haptics) took priority. Worth raising once a human confirms steering itself works.
5. **Traffic still doesn't react to the player or to itself** — unchanged since session 1.
6. **Try `tools/generate_track.py` with other hosted models** (`qwen2.5-coder:7b`,
   `kimi-k2.7-code`) as foils, compare pass rate/course quality against `qwen3-coder` —
   still not done.
7. **Project card PR to the class repo** — already opened this session
   (`mfadt/sld-fall-2026` PR #20, project card + index row for freracer, status
   "prototype"). Update its status once there's a real human playtest result to report;
   don't forget freracer itself is currently a **private** repo, so it won't show up in
   the `topic:sldllm-f26` showcase search until/unless that's made public.

## Gotchas learned the hard way

- **Forking the game process itself for any per-frame or high-frequency side effect is
  expensive on this hardware.** This bit us for haptics (`dbus-send` from inside the
  pygame process). If a future feature needs frequent subprocess calls (network, other
  D-Bus services, etc.), spawn a small long-lived helper early and talk to it over a
  pipe, the way `buzz_helper.py` does now — don't fork the big process per event.
- **Silent `except Exception: pass` around device I/O hides real permission bugs.**
  The vibrator-write failure (root-only sysfs path, game runs as `user`) was invisible
  for an entire session because the write was wrapped in a bare except. If something
  "does nothing" on real hardware, check permissions/exit codes directly over SSH before
  assuming it's a tuning problem.
- **Verify hardware assumptions (which accelerometer axis, which colors actually read
  correctly) empirically, on the device, before trusting a "same convention as the other
  project" copy-paste** — fremarble's tilt convention was right for fremarble's own grip
  and screen orientation, not for this one.
- Ollama's `/api/generate` against `qwen3-coder:30b-a3b-q4_K_M` on the CPU-only
  `sld-cloud` node took several minutes per track; `tools/generate_track.py` uses a 900 s
  timeout — budget for that when scripting model comparisons.
- The laptop's OpenSSL 3.5 refuses the N900's `ssh-rsa`/legacy KEX/cipher suite outright
  ("error in libcrypto") unless `OPENSSL_CONF` points at a config with
  `CipherString = DEFAULT@SECLEVEL=0`. The existing `~/.local/bin/n900` shim already
  handles this — use it rather than raw `ssh`/`scp` (pass the same options directly to
  `scp`, since `ProxyCommand` nesting doesn't propagate them correctly).
