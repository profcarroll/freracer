# Handoff — end of session 1

For the next session, whoever holds the keyboard: a person or an assistant.

## Where things are

| Thing | Where |
|---|---|
| This repo | `github.com/profcarroll/freracer` (private) |
| Working copy on the device | `/home/user/MyDocs/freracer/` on the N900 |
| N900 access | laptop shortcut `n900` (root over legacy SSH crypto, same shim as fremarble). IP 10.0.0.70 by DHCP. |
| Cloud node | `ssh sld-cloud`. Ollama on 127.0.0.1:11434. `qwen3-coder:30b-a3b-q4_K_M` is the
  track designer — reach it from the laptop with `ssh -L 11434:127.0.0.1:11434 sld-cloud`. |
| Sibling project | `fremarble` — same device, same course, same conventions. |

## The rule

**Bytes to atoms.** Assistants produce text. Nothing runs on the device until a person (or the
directing assistant, by hand, over SSH) has read it and carried it there.

## What happened, in order

1. Scaffolded the repo directly from fremarble's proven conventions: `.trk` text format
   (mirrors `.lvl`), `track.py` (mirrors `level.py`), `telemetry.py`, `bot_steer.py`
   (mirrors `bot_tilt.py`), same Python-2.5-safe bootstrap.
2. Chose a pseudo-3D scanline renderer (OutRun/Pole Position style) over top-down, at the
   user's request, accepting the performance risk on a 600 MHz Cortex-A8.
3. Designed the track format around short `ROAD <segments> <curve> <hill>` stretches,
   eased in/out so an LLM's output can't produce a kinked, unplayable road, instead of
   raw per-segment geometry.
4. Built `game.py`: classic relative-to-camera perspective projection, road/rumble/lane
   bands, static obstacles, looping AI traffic, accelerometer steering (same raw_y /
   calibration / dead-zone / smoothing convention as fremarble), automatic throttle,
   vibrator haptics on curb, grass, obstacle and traffic contact.
5. Wrote `tools/racer_fps.py` (mirrors `tools/marble_fps.py`) and ran it **on the real
   N900** over the `n900` SSH shim (the user explicitly authorized device access for
   this session, overriding the default "bytes to atoms, no assistant SSH" convention):
   - `DRAW_DISTANCE=160`: 36 avg / **19 worst** fps — rough.
   - `DRAW_DISTANCE=120`: 50 avg / **49 worst** fps — smooth. Locked in as the default
     in both `track.py` and `game.py`.
6. Byte-compiled every file with `python2.5 -m py_compile` on-device (all OK) and ran
   `test_track.py` on-device (PASS).
7. Ran the full `game.py` loop on-device with `bot_steer.py`:
   - Neutral tilt (no steering) the whole lap: finished cleanly in 9.8 s at 6000 u/s top
     speed, offset drifted only ~9 units off centre even through the sharpest corner
     (curve 5). **Centrifugal force is currently too weak to matter** — cornering does
     not require counter-steering yet. `CENTRIFUGAL = 0.0007` needs raising for an
     arcade "the car pulls outward in corners" feel.
   - A scripted alternating-tilt run walked the car ~8700 world units off the road
     (deep into the padded grass) before a fix landed. Found and fixed two real bugs
     along the way (both are already applied, not left for later):
     a) the grass-zone speed penalty was applied *after* that frame's `player_z`
        integration, so telemetry showed `speed=0` while the car kept crawling forward —
        reordered so the zone penalty affects the same frame's movement.
     b) there was no bound on lateral drift once off-road; added a hard clamp at
        `width * 3` so a missed corner is always recoverable.
8. Generated a second track with `tools/generate_track.py` against `qwen3-coder` on
   `sld-cloud` (over an SSH tunnel from the laptop) — **passed validation on the first
   attempt**: `tracks/002-night-circuit.trk`, 435 real segments, dusk-city theme, 4
   obstacles, 4 traffic cars. Also validated on-device.

## Next steps, in order

1. **A human needs to actually drive it** — with accelerometer steering, not a script.
   Play-test 1 doesn't exist yet. Tune `STEER_GAIN`, `CENTRIFUGAL`, `MAX_SPEED` from
   that telemetry the way fremarble tuned marble physics from `telemetry/human*.csv`,
   not from a hand not yet on the device.
2. **Raise `CENTRIFUGAL`** (see finding above) so hard corners actually require
   correction, then re-test with a scripted bot whose tilt is derived from the track's
   own curve sequence (not guessed, like the first attempt here) to sanity-check before
   the next human session.
3. **Try `tools/generate_track.py` with `qwen2.5-coder:7b` and `kimi-k2.7-code`** as
   hosted-model foils, same prompt, compare pass rate and course quality — fremarble's
   "hosted foil" comparison, not yet done here.
4. **Traffic doesn't react to the player or to itself.** Fine for v1; revisit if it
   causes unfair blind hits once a human is driving.
5. Set the N900's clock so default telemetry filenames are honest (same fremarble gotcha).
6. Project card PR to the class repo, once there is a play-tested result to report.

## Gotchas learned the hard way (new to this project)

- Ollama's `/api/generate` against `qwen3-coder:30b-a3b-q4_K_M` on a 4-core CPU-only
  Ampere A1 node took several minutes for one track; the first attempt timed out a
  300 s `urllib` request. `tools/generate_track.py` now uses a 900 s timeout — budget
  for that when scripting comparisons across models.
- The laptop's OpenSSL 3.5 refuses the N900's `ssh-rsa`/legacy KEX/cipher suite outright
  ("error in libcrypto") unless `OPENSSL_CONF` points at a config with
  `CipherString = DEFAULT@SECLEVEL=0`. The existing `~/.local/bin/n900` shim already
  handles this — use it rather than raw `ssh`.
