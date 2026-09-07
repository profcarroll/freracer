# Handoff — end of session 2

For the next session, whoever holds the keyboard: a person or an assistant.

**Bottom line: not yet fun to drive.** Session 1 built it; session 2 was a real human
playtest that found the steering axis was wrong, haptics silently never fired, the road
was nearly invisible, and fixing haptics naively caused a real stutter. All four are
fixed and bot-verified, but **no human has driven the corrected build yet.** Don't trust
any of `MAX_SPEED` / `STEER_GAIN` / `CENTRIFUGAL` / `DRAW_DISTANCE` until someone does.

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

## Next steps, in order — "a fresh approach"

The user asked for a fresh approach next session rather than more one-bug-at-a-time
patching. Suggested starting point:

1. **Play it. Actually drive it, on the corrected build, before touching any more code.**
   Don't guess at `STEER_GAIN`/`CENTRIFUGAL`/`MAX_SPEED` — every constant in `game.py` is
   still session-1 guesswork that's never been felt by a human hand. If it's still not
   fun or not controllable, that telemetry (now that `raw_x` is the real steering signal)
   will actually mean something, unlike session 1's bot-only runs.
2. **Consider instrumenting *before* re-tuning by feel.** e.g. log the actual `raw_x`
   range during a real drive (not a synthetic roll test) so `STEER_GAIN`/`TILT_DEAD_ZONE`
   are picked from real driving-grip data, not the one 22-second sample from this
   session's axis discovery.
3. **Re-examine whether the whole visual language needs a bigger rework**, not just
   color tweaks. This session raised contrast and added shoulder bands + roadside poles,
   but "the track detail is so sparse" may point at needing denser/more varied track
   content too (tighter chicanes, more elevation change) — that's still untouched from
   session 1's two tracks (`001-autumn-hills.trk` hand-built, `002-night-circuit.trk`
   AI-generated), not re-evaluated after the rendering changes.
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
