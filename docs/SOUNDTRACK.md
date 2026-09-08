# freracer: the soundtrack

What the N900 can do with sound from Python 2.5, measured on the device on
2026-09-07, and the procedural synthesizer built on top of it: `synth.py` (the
soundchip), `music.py` (the composer and the stream that feeds the mixer),
`tools/render_song.py` (hear it on the laptop). Written against commit `5468a37`
(phase 1 of the infinite road merged), on the `soundtrack` branch.

## 0. The short version

- **MIDI is a dead end on the device.** `pygame.midi` builds against portmidi and
  finds zero devices; there is no `/dev/snd/seq`, no timidity, no fluidsynth, no
  soundfont. MIDI would need an external synth over USB host, which the N900
  does not have. So the synthesizer is ours.
- **Pure-Python sample synthesis is out** (18 µs a sample, 40% of the CPU for one
  voice), **but `audioop` and `array` are in**: add, multiply, resample and
  stereo-fold run at C speed, a few milliseconds per second of audio. A note
  costs ~10 ms to render once and is cached; a beat of music is ~7 `audioop.add`
  calls. The SDL mixer then mixes and plays it in its own thread.
- **The expensive part is not ours.** PulseAudio, Nokia's system-mode build with
  the music post-processing chain, takes **about a third of the CPU whenever any
  stream is playing anything**, one channel or six, mono or stereo, 11 kHz or
  48 kHz. Only the SDL buffer size moves it: 512 samples costs 65% of the frame
  rate, 4096 costs 30%, and nothing above 4096 helps. There is no cheaper sink
  to route to. The soundtrack therefore costs the game roughly **26 → 21 fps**,
  and `--mute` exists.
- **It sounds like this:** every region of the infinite road is a style
  (key, tempo, scale, drum feel, bass pattern, instruments). Speed adds layers
  (drums+bass → +pad → +lead → +16th hats). Corners you are about to enter get
  a snare roll and a crash on entry; bends steer the melody's contour; hills
  push the lead's register; grass and shoulders drop the arrangement to drums
  and bass; a collision plays a cluster and the lead sits out two bars;
  a region change is a crash and a new key. Same seed, same song.

## 1. What the device has

| | |
|---|---|
| Codec | TLV320AIC3x on the RX-51 board, stereo speakers, 3.5 mm jack, FM transmitter (si4713, sysfs at `/sys/class/i2c-adapter/i2c-2/2-0063/`) |
| ALSA | card 0 `RX51`, `pcmC0D0p`/`pcmC0D1p`; the default PCM is the PulseAudio plugin (`/etc/asound.conf`) |
| PulseAudio | 0.9.15, `--system --high-priority`, realtime priority 5, sink at 48 kHz s16le, `resample-method = speex-fixed-2`, 2 × 20 ms fragments |
| Policy | `/etc/pulse/xpolicy.conf`: streams are classed by process name (`x-maemo-match.table`); everything that is not the phone stack is class `x-maemo` and goes to `sink.music`, i.e. through Nokia's post-processing chain. Only `telepathy-stream-engine`, `tonegend` and `voicehost` reach `sink.voice.raw`. Opening `hw:0,0` directly fails: pulse owns it. |
| SDL | 1.2.13 (maemo8), SDL_mixer 1.2.6, default audio driver is pulse; `alsa` and `esd` both land in pulse anyway |
| Python | 2.5.4 with `audioop`, `array`, `struct`, `wave`, `cStringIO`; **numpy 1.4.0 is installed** (651 ms to import, 7 MB RSS); pygame 1.9.1 with `mixer`, `sndarray` (numpy) and `midi` (0 devices) |
| Memory | 245 MB total, ~22 MB free with the desktop up, 37 MB of swap in use |

## 2. Measurements

All on the N900, Python 2.5.4, 22050 Hz mono int16 unless stated. Scripts were
one-off probes; the numbers that matter are folded into the code comments.

### 2.1 Synthesis cost

| Operation | Cost |
|---|---|
| Pure-Python loop, one sawtooth voice, 1 s | 544 ms |
| Pure-Python wavetable lookup, 1 s | 394 ms (listcomp + `map`: 347 ms) |
| numpy `sin` over 1 s (float32) | 222 ms |
| numpy int16 table lookup, 0.4 s note | 3.3 ms (with a float envelope: 25.7 ms) |
| `array * n` single-cycle replication, 1 s | 3.6 ms |
| `audioop.add` + `mul` + `tostereo`, 1 s | 14.3 ms |
| `audioop.ratecv` ×1.5 / ×0.7, 1 s | 6.6 ms / 4.1 ms (cost scales with *input* length) |
| Envelope as chunked `audioop.mul` (512-sample steps), 1 s | 6.9 ms |
| One beat block: 12 adds + `tostereo` | 9.3 ms; `pygame.mixer.Sound` from it 0.5 ms |
| One 0.4 s note the way `synth.tone` does it (integer-period cycle, replicate, ratecv near ratio 1, envelope, WAV) | ~10 ms (measured 48 ms when ratecv was fed a 2048-sample table per cycle: input length is what it charges for) |

Python 2.5 on this 32-bit ARM has 31-bit ints; a multiplication that spills
into `long` runs an order of magnitude slower. The noise LCG in `synth.noise`
is 16-bit for that reason (it went from 700 ms to negligible).

`audioop.add` and `mul` **clip** at ±32767 on 2.5.4, they do not wrap
(checked: 30000 + 10000 → 32767).

### 2.2 pygame.mixer

- `mixer.init(22050, -16, 2, N)` takes 40–95 ms. 8 channels. `Channel.queue()`
  is gapless: 40 queued 50 ms clips kept the channel busy for 2.000 s. SDL_mixer
  1.2.6 calls the channel-finished hook inside its mixing loop and keeps filling
  the same buffer from the next chunk.
- `Channel.play()` costs a few µs.
- **The mixer runs ahead of the speaker.** With the 4096-sample buffer, the
  first `play()` on a fresh stream is consumed whole within 20 ms (PulseAudio
  pre-fills about half a second), and after that `Channel.get_busy()` goes
  false and `get_queue()` empties roughly 0.4 s before the audio is heard. So
  the channel flags say what the mixer has *consumed*, not what is playing;
  `music.Stream` keeps its own count of seconds handed over. It also means a
  one-shot (`hit`, `curb`) is heard ~0.4 s after `play()`. With a 512-sample
  buffer the lead is ~50 ms, at three times the CPU cost.
- **`pygame.mixer.Sound(<str>)` is a trap.** On 1.9.1 it builds a valid Sound
  from a raw byte string, but if the string contains a null byte it also leaves
  a `TypeError("argument 1 must be string without null bytes")` pending in the
  interpreter, which surfaces at the next unrelated C call: `audioop.ratecv`,
  in practice, two probes in a row. `Sound(buffer=...)` does not exist in 1.9.1.
  `synth.make_sound` therefore wraps the PCM in a 44-byte WAV header inside a
  `cStringIO` (3 ms). `sndarray.make_sound` would also work but needs numpy
  imported.

### 2.3 What audio costs the renderer

`tools/racer_fps.py` probe (session 3 renderer, synthetic lap, `DRAW_DISTANCE`
120, `MIN_BAND_HEIGHT` 3), 8–12 s runs, with the mixer playing a looping sine
on N channels:

| Mixer state | avg fps | worst second |
|---|---|---|
| no mixer | 33.7–36.2 | 28.0–28.9 |
| mixer initialised, nothing playing | 36.1 | 29.0 |
| 22050 stereo, buffer 512, 1 channel | 12.5 | 11.8 |
| 22050 stereo, buffer 512, 6 channels | 13.1 | 12.6 |
| 11025 **mono**, buffer 512, 6 channels | 13.2 | 12.9 |
| 44100 stereo, buffer 1024, 6 channels | 8.3 | 7.6 |
| 48000 stereo, buffer 1024, 6 channels | 10.4 | 10.2 |
| 22050 stereo, buffer 1024 | 12.7 | 12.3 |
| 22050 stereo, buffer 2048 | 10.9 | 10.4 |
| **22050 stereo, buffer 4096** | **24.2–25.9** | **20.7–25.3** |
| 22050 stereo, buffer 8192 | 24.8 | 24.2 |
| 22050 stereo, buffer 16384 | 24.9 | 24.6 |
| 22050 mono, buffer 4096 | 26.1 | 25.8 |
| 48000 stereo, buffer 8192 | 24.6 | 24.2 |

Reading: one channel costs the same as six, mono the same as stereo, 11 kHz the
same as 48 kHz. `top` during a run shows `pulseaudio` at 35% CPU and the game
falling to what is left. The cost is per-fragment work in PulseAudio's sink
chain, and the stream's requested latency (which SDL derives from the buffer
size) sets how often that runs; 4096 samples (186 ms) is the knee. Silence is
free, so the mixer can stay initialised.

With the actual soundtrack (`music.py`, everything playing), same probe on the
journey generator:

| | avg fps | worst second |
|---|---|---|
| `racer_fps.py 12 --journey 4471` | 25.8 | 24.4 |
| `racer_fps.py 12 --journey 4471 --music` | 23.5 | 17.8 |
| full game loop, bot, 30–45 s, `--journey 4471 --mute` | 25.7 | |
| full game loop, bot, 30–45 s, `--journey 4471` (music) | 21.2–21.6 | |

The synth's own share is the difference between the pulse tax and these
numbers: a few percent. `Music.update` is budgeted at 4 ms a frame, 10 ms
while no beat is rendered ahead, 24 ms when the queued beat is about to run
out. A cache miss (a note not yet rendered) is one uninterruptible step of
10–60 ms; the worst step seen on the device was 130 ms at a style change.

## 3. Design

### 3.1 The soundchip (`synth.py`)

Retro is not an aesthetic choice here; it is what is cheap. A chip voice is a
single cycle repeated with a gain envelope, and that is exactly what `array`
and `audioop` do fast.

- **Wavetables**: 1024-entry int16 tables for `saw`, `square`, `pulse25`,
  `pulse12`, `tri`, `sine`, `organ` (three drawbars). Not band-limited; the
  aliasing on high saw notes is the sound of the era.
- **`tone(wave, hz, n)`**: one integer-period cycle (P ≤ 400 Python lookups),
  `array * reps`, then `audioop.ratecv` from `SR/P` to the exact pitch. The
  ratio is within 1% of 1.0 so input and output are the same size; that is the
  whole trick to keeping ratecv cheap.
- **`envelope`**: attack/decay by chunked `audioop.mul`: 64-sample steps for
  the first 20 ms, 256 to 0.3 s, 512 after. Steps are inaudible on a decay and
  audible on an attack, hence the split.
- **Instruments** (`INSTRUMENTS`): wave + envelope + length + gain + optional
  detune (a second copy a few cents sharp, mixed in: chorus for `sawlead`,
  `organ`, `brass`). Eleven of them.
- **Drums**: one deterministic 12k-sample noise buffer; hats and crash are its
  first difference (a free high-pass) under a decay; the rumble is a running
  mean (a free low-pass); the snare is noise plus a 185 Hz square; the kick is
  the one Python loop, a 0.2 s pitch sweep rendered once.
- **Caches**: `NoteBank` per (instrument, midi, gain-in-1/16ths), capped at 200
  entries (~4 MB); `DrumKit` per (kind, gain). Gains are baked into the cache so
  the mixer never multiplies.
- **`Mixdown`**: one beat as three mono pan groups (`c` centre: drums+bass, `l`
  lead, `r` pad/arp). `add(group, offset, data)` is three slices and one
  `audioop.add`; a tail past the block goes into a carry that seeds the next
  block. `stereo()` folds the touched groups with `tostereo` and adds them.
  `premix()` turns a list of (offset, sample) into one sample: how a whole drum
  beat, a chord and an arpeggio each become a single add.
- **`make_sound`**: WAV-in-`cStringIO` → `pygame.mixer.Sound`, see 2.2.

### 3.2 The stream (`music.Stream`)

Sample-accurate timing without threads. A beat is rendered as a Python
generator (`Music._render_block`: plan, drums, chords, notes, fold, Sound, one
`yield` per expensive step) and `Stream.update(budget)` advances it a few steps
per frame. Finished beats sit in `ready`; `_feed` hands them to channel 0 with
`play()` the first time and `queue()` after that. SDL swaps to the queued
sound at the exact sample the current one ends.

Pipeline depth: playing + queued + one ready ≈ three beats ≈ 1.3–1.7 s, plus
PulseAudio's ~0.4 s. That is the delay between the composer's decision and the
speaker, so the composer is fed the road **1.2 s ahead of the car** (`NOW_S`),
and 3 s ahead (`SOON_S`) for build-ups. `Stream.urgent()` (nothing ready and
the audio handed over ends within 0.35 s) multiplies the budget by six for that
frame. A starve (the mixer idle with the handed-over audio about to run out) is
counted and restarted, and reported as `MUSIC ... starves=` after the `RESULT`
line; the bot journey shows 0.

Three beats are rendered synchronously at init (`prime`), so playback starts
before the first frame with a beat in hand. Music init on the device: ~0.9 s
(drums 0.35 s, hit/curb/grass one-shots 0.08 s, 0.4 s of note pre-rendering,
three beats 0.05 s). It runs before `t0` so it
cannot eat the tilt calibration window. The finish fanfare renders when the
finish line is crossed, not at startup.

### 3.3 The composer (`music.Composer`)

Input each beat: `ctx` from `music.road_context(win, z, speed, ...)`:

| field | from | drives |
|---|---|---|
| `speed` 0..1 | `speed / MAX_SPEED` | intensity level (0: drums+bass; 1: +pad/arp; 2: +lead; 3: +16th hats), tempo ±8% |
| `curve` | segment 1.2 s ahead | melody contour (right bend: phrases climb; left: fall), arpeggio direction |
| `slope` | `y` 30 segments further on, ±1 | lead register up a third on a climb, down on a descent |
| `surface` | grass / offroad / curb / road | anything but road drops to level 0 |
| `region`, `soon_region` | chunk log 1.2 s / 3 s ahead | style switch with a crash and a key change; thinning (no pad, no hats) while a transition is coming |
| `motif`, `soon_motif` | chunk log | hairpin/switchback/corner coming: snare roll for up to two bars, no lead; on entry: crash |

State: bar, beat, chord, a 2-bar phrase cache, intensity with hysteresis,
`hit_rest`, `tension`, `arp_i`. Everything random is `rng.Rng(seed, beat)` so
a seed replays its soundtrack on the laptop and the device.

- **Styles** (`STYLES`), one per region, plus `THEME_STYLE` for the two `.trk`
  themes: farmland is a major-pentatonic country shuffle at 108 with a walking
  triangle bass and a 25% pulse lead; foothills a dorian rock groove at 122
  with an 8th-note saw bass and brass stabs; mountains a minor 138 with
  octave-jumping saw bass, a detuned saw lead and a 16th-note pulse arpeggio;
  coast a lydian bossa at 96; highway mixolydian 130 with octave bass (OutRun);
  strip and city are funk (minor pentatonic / minor); small-town is a waltz in
  3; valley and lake are slow major with organ pads; river is a dorian 6/8 with
  arpeggios. Each has a key offset from the home key so region changes modulate.
- **Harmony**: per-scale chord sets with weights; a weighted walk that goes
  home every fourth bar.
- **Melody**: a 2-bar phrase per (8-bar period, letter) in AABA form: Euclidean
  onsets (k from density, intensity and letter), a random walk on the scale
  biased by the bend, reflected at the range edges, snapped to chord tones on
  beats 1 and 3, transposed by the hill.
- **Bass**: five patterns (walk, drive, octave, funk, oom-pah); level 0 keeps
  only the downbeat of each beat.
- **Drums**: three levels per feel, 16 or 12 steps; a fill on the last beat of
  every fourth bar; the whole beat is pre-mixed and cached by (feel, level,
  beat, fill, thin, bpm).
- **Pad**: held per bar (organ), stabbed on the off-beats (brass), or on beats
  2 and 3 (waltz); pre-mixed per chord.
- **Arp**: chord tones plus the octave, one per sixteenth, up on a right bend
  and down on a left; pre-mixed per (chord, bpm).

Tempo is quantised to 3 bpm so the caches key on it.

### 3.4 One-shots (`Music.event`)

Immediate, on channels 1–3, not through the beat pipeline: `hit` (a semitone
cluster + snare + crash, and the lead rests two bars), `curb` (a click) and
`grass` (a low rumble) on the same 0.35 s debounce as the vibrator, `finish`
(fade the music, arpeggio into a chord). Latency is PulseAudio's pre-buffer,
~0.4 s (see 2.2); the vibrator already covers the instant.

### 3.5 In the game (`game.py`)

- `pygame.mixer.pre_init(*music.MIXER_ARGS)` before `pygame.init()`.
- `music.Music(seed, win.region_at(0))` right after telemetry opens, before `t0`.
- Every frame after physics: `snd.update(music.road_context(...))`.
- `snd.event(buzz_key)` wherever the vibrator fires; `snd.event('finish')`;
  `snd.stop()` on any other outcome.
- `--mute` anywhere on the command line, or `FRERACER_MUTE=1`, runs without it.
  A music failure prints a traceback and continues muted.
- `RESULT` is followed by `MUSIC blocks= starves= renders= worst_step_ms=`;
  telemetry's summary gains `music_starves`.

### 3.6 Hearing it without the device

```
python3 tools/render_song.py --seed 4471 --seconds 120 --out /tmp/seed4471.wav
python3 tools/render_song.py --regions mountains,city --seconds 30
python3 tools/render_song.py --track tracks/002-night-circuit.trk
```

Same generator, same window, a toy driver that lifts for corners, the real
`Music` with an offline channel, one-shots overlaid. `tools/fake_audioop.py`
stands in for the `audioop` module Python 3.13 removed. On the device,
`python2.5 music.py 30 4471` plays a journey with no display and prints the
init breakdown and stream stats; `python2.5 music.py 20 1 mountains,city`
auditions styles.

## 4. What was tried and rejected

- **Per-note `Channel.play()` from the frame loop** (the NES/SNES driver
  model): zero render cost, but every note lands on a frame boundary, and at
  22 fps a sixteenth note at 130 bpm is 2.5 frames, so the groove would swing
  by ±23 ms permanently. The block stream costs ~4 ms a frame and is
  sample-accurate.
- **numpy on the device**: present, and 3 ms for a table-lookup note, but 651 ms
  and 7 MB to import, 26 ms a note once a float envelope is involved, and
  nothing `audioop` cannot do at the same speed. Not used at runtime.
- **Bypassing PulseAudio** (`SDL_AUDIODRIVER=alsa AUDIODEV=hw:0,0`): fails,
  pulse holds the device. Masquerading as `tonegend` to reach `sink.voice.raw`
  would route the game to the earpiece path under call-volume limits. Not done.
- **Bigger SDL buffers than 4096**: no further gain, only latency.
- **Cutting notes to their written length with a fade**: four extra `mul`s per
  note for nothing a chip ever did. Notes ring for their instrument's length.

## 5. Open

- **Nobody has listened on the device's speakers.** Every level in this file
  was set from the WAV. The hats may be too bright or too quiet on the N900's
  small speakers; PulseAudio's chain has its own EQ. First thing to do with the
  device in hand: `python2.5 music.py 20 1 farmland,mountains`.
- **The pulse tax.** 21 fps with music against 26 without. Headphones or the FM
  transmitter may skip the speaker-protection stage of the chain and cost less;
  untested. If the frame rate matters more than the music, `--mute`.
- **Style tuning is guesswork** the way the region curve ranges were: the
  tempos, densities and instrument choices in `STYLES` are a first draft that
  has been heard as WAV, not driven to.
- **Corner anticipation depends on the chunk log**, so on a finite `.trk` there
  is one chunk called `track` and no rolls. Tagging `.trk` stretches with a
  motif would fix that.
- **Traffic is silent.** A passing car could be a pitch-bent saw on channel 4,
  the way OutRun did it.
- **The LLM's role**: styles are data (`STYLES`, `DRUMS`, `BASS`). A `.sty` text
  format under the same parsing rules as `.trk` would let `qwen3-coder` propose
  a region's music the way it proposes its road, and `render_song.py` is the
  validator. Not built until a region's road is worth a style.
