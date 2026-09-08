# freracer: the infinite road

Spec for turning freracer from "one lap of one track" into an endless, procedurally
generated drive across a changing country. Written 2026-09-07 against commit `575a52e`
(after the session 3 renderer rebuild, PR #1).

## 0. The pitch

You start the car and drive. The road never ends. It starts somewhere and gradually
becomes somewhere else: a coast road turns into a harbour town, the town gives way to
farmland, a highway with rest stops and strip malls carries you toward a city, the city
thins into suburbs, the land rises into foothills and switchbacks over a mountain pass,
drops into a valley, follows a river, skirts a lake, and arrives at another small town.
Every drive is different. You never know where you'll end up, but everywhere you end up
is a recognisable *kind* of place, because the kinds are designed and tested, and only
the sequence and the details are rolled.

The game stops when you tap the screen. The result is a journey log: how far you drove,
where you went, what you hit.

## 1. What this changes, in one table

| Today | Infinite road |
|---|---|
| One `.trk` file, loaded whole at start | A seeded generator that produces road a chunk at a time, just ahead of the camera |
| `THEME` is one global palette | A **region** state machine: coast, farmland, highway, strip, small town, city, foothills, mountains, valley, river, lake; palettes and road character blend at region boundaries |
| Finish line, `PAR`, lap time | No finish line. Odometer, journey log, regions visited, distance as the score |
| Traffic loops the lap on a timer | Traffic spawns ahead of the player per region density and is dropped behind |
| The LLM designs whole tracks | The LLM designs **chunks** (region + motif exemplars) offline; the device stitches and varies them at runtime with no network |
| Two tracks | A curated library of tested chunks, plus a parametric fallback so the road is infinite even with zero library files |

The existing `.trk` path stays. `game.py tracks/001-autumn-hills.trk` remains a finite
lap; `game.py --journey [seed]` is the new default from the desktop launcher.

## 2. Ground truth: what the current code lets us do

Everything below has to run in **Python 2.5.4 + pygame 1.9.1 on a 600 MHz Cortex-A8
with 245 MB RAM**, with no network at runtime. The relevant pieces of the current code:

- `track._build_segments` expands `ROAD <segments> <curve> <hill>` stretches into a flat
  list of `{'curve', 'y', 'width', 'x'}` dicts, easing curve in and out over each
  stretch and easing height with smoothstep. Curve starts every stretch at 0 and ends
  near 0; `y` is continuous by construction. **This means any two stretches join
  smoothly, which is the property the whole chunk-stitching design rests on.**
- `track.segment_at(trk, z)` and `game.draw_road` index the flat list by
  `int(z / SEGMENT_LENGTH)`. Both need a window with a base offset instead.
- Since session 3 the renderer is the standard Super Scaler treatment: it walks
  near-to-far, re-accumulates the centreline offset from `curve` every frame starting at
  the camera, projects lateral offsets only, and folds sub-`MIN_BAND_HEIGHT` bands
  together. Ground is drawn per band as full-width `screen.fill` stripes, sky is a
  startup surface blitted clipped to the rows above the road, and a procedurally
  generated 96-row horizon backdrop (`build_backdrop`, seeded by the tiny `_Rng` LCG)
  pans with the road's heading. Depth haze is pre-blended per distance at startup by
  `build_palette` so the frame loop only indexes lists. All of this is what a region
  palette has to plug into (§5.3).
- **The device charges per draw call, not per pixel**: roughly 90 µs a call, measured.
  The full game loop runs about 22–24 fps on `001-autumn-hills` at `DRAW_DISTANCE=120`,
  `MIN_BAND_HEIGHT=3`. Every rendering idea in this spec is costed in draw calls.
- `track.py` still bakes an absolute centreline `x` into each segment. The renderer no
  longer projects it; its only remaining use is the first difference (the heading) that
  pans the backdrop. On an infinite road the window should carry a per-segment heading
  instead of an unbounded absolute `x`.
- Traffic position is `(base_z + speed * t) % lap_length`. There is no lap in a journey.
- A clean lap of the 480-segment tracks takes 8–12 s at `MAX_SPEED`. The handoff calls
  lap length versus `MAX_SPEED` the biggest open design question. An infinite road
  dissolves the lap-length half of it; the speed half still sets every "segments per
  second" figure below.
- `tools/generate_track.py` takes minutes per call against `qwen3-coder` on `sld-cloud`.
  The model cannot be in the runtime loop. Its job moves to offline library curation.
- `track.validate` is the only quality gate today. It checks discontinuities, ranges and
  types. It does not check whether a stretch is drivable.

### 2.1 The coordinate model, and what it means for `curve`

This spec was first drafted against `d85e5e6`, where `_build_segments` integrated an
absolute centreline `x` and the renderer projected it against a road-relative camera, so
the road left the screen after the first sweeper (by segment 119 of Autumn Hills the
centreline was 4,620 units right, projecting ~16,000 px off-screen). Session 3 found and
fixed that independently, along with the far-to-near band-culling bug and the matching
absolute-versus-relative confusion in the collision tests. `player_x` is now the single
road-relative lateral coordinate for zones, collisions and the camera, which is exactly
the model an infinite road needs. Nothing in this spec has to fix it; the window design
in §5 simply never bakes an absolute `x` in the first place.

One consequence carries forward. `curve` is angular **acceleration**, not angle: a
`ROAD 70 3 0` stretch bends harder and harder for 70 segments. Both existing tracks were
authored blind, so the region curve ranges in §4.3 are provisional until someone has
driven the fixed renderer and reported what a `3` and a `6` feel like. Expect the ranges
to come down, and expect long stretches to want lower values than short ones.

## 3. Vocabulary

| Term | Meaning | Size (at today's `MAX_SPEED` 6000 u/s ≈ 60 segments/s) |
|---|---|---|
| **segment** | one 100-unit band of road with `curve`, `y`, `width`, region tag | 1/60 s |
| **stretch** | one `ROAD` line: N segments with one eased curve and hill | 0.3–1.5 s |
| **chunk** | 4–12 stretches with obstacles, traffic hints and scenery: one "thing the road does" (a hairpin, a bridge, a main street) | 150–450 segments, 3–8 s |
| **motif** | the abstract shape a chunk instantiates: sweeper, esses, hairpin, crest, straight, switchbacks, bridge, main-street, rest-stop… | |
| **region** | an environment: palette, horizon, scenery set, road character, motif weights, traffic density | 6–15 chunks, 40–120 s |
| **transition** | a special chunk generated between two regions that blends palette, width and scenery density | 1 chunk |
| **journey** | the infinite sequence of chunks for one seed | ∞ |

All time figures scale with `MAX_SPEED`, which the handoff says is untuned. Sizes in this
spec are stated in segments; retune the segment counts if cruise speed changes.

## 4. The generator

### 4.1 Determinism

- A journey has one integer **seed**. Default: `int(time.time())`. Override:
  `game.py --journey 12345`. Printed in the `RESULT` line and telemetry summary so a run
  can be replayed or shared ("try seed 4471, the mountain pass is brutal").
- The region chain and chunk `k` are derived from `_Rng(seed * 1000003 + k)`, the same
  tiny LCG `game.py` already uses for the backdrop and for the same reason: its stream is
  identical on the device's Python 2.5 and the laptop's Python 3, which `random` does not
  promise (`randrange` changed in 3.2). Move `_Rng` into its own module so `track.py`,
  the generator and the tools share it. Chunk `k` therefore depends only on
  `(seed, k, region_state_at_k)`, and `region_state_at_k` is itself a pure function of
  the same seeds.
- No wall-clock or frame-rate input touches generation. The same seed on the device and
  on the laptop produces the same road, which is what makes `tools/journey_dump.py`
  (§9) a valid offline test.

### 4.2 Region state machine

A weighted Markov chain with dwell limits. Each region has `dwell_min`/`dwell_max` in
chunks; while dwelling, the next chunk is drawn from the region's motif weights. When
dwell expires, a successor is drawn from the weighted successor list, and a **transition
chunk** is emitted between the two.

```
coast       -> farmland 3, small-town 3, highway 2, foothills 1
farmland    -> small-town 3, highway 3, river 2, foothills 2, lake 1
highway     -> strip 3, city 2, farmland 2, valley 1, mountains 1
strip       -> city 3, highway 2, small-town 1
city        -> highway 3, strip 2, river 2
small-town  -> farmland 3, river 2, lake 2, highway 2, coast 1
foothills   -> mountains 4, valley 2, lake 1
mountains   -> valley 4, foothills 2, lake 1
valley      -> river 3, farmland 3, small-town 2, foothills 1
river       -> small-town 3, valley 2, farmland 2, city 1
lake        -> small-town 3, foothills 2, farmland 2, coast 1
```

Rules on top of the chain:

- **No immediate return** (A→B→A) unless A is `highway` or `farmland`, which are the
  connective tissue of the country and are allowed to recur.
- **Long-term variety:** a region that has been visited in the last 4 regions has its
  weight halved. Every region is reachable from every other within 3 hops (check in
  `test_journey.py`).
- **Journey start:** the first region is drawn uniformly from `{coast, farmland,
  small-town, highway}`; these are the gentlest openers. The first chunk is always a
  plain straight of 120 segments so the calibration window (`CALIBRATION_WINDOW`) and
  the first second of acceleration happen on easy road.
- **Time of day** (optional, §11): a separate slow clock that advances with distance,
  dawn → day → dusk → night → dawn over ~10 minutes of driving, tinting sky and ground.
  `dusk-city` today is just `city` at `dusk`.

### 4.3 Road character per region

The renderer is minimal, so a region has to be recognisable through **what the road
does**, not just what colour the grass is. This table is the heart of the design. Values
are starting points to be tuned by driving.

| Region | Width | Straights (segs) | Curve range | Hill amplitude (units/stretch) | Motif weights | Traffic (cars/1000 segs, speed) | Obstacles | Scenery (per side) | Horizon | Ground / sky |
|---|---|---|---|---|---|---|---|---|---|---|
| **coast** | 1000 | 60–120 | ±1.5–3.5, long | 100–250, rolling | sweeper 5, straight 3, esses 1, crest 1 | 6, medium | rock (seaward shoulder) | seaward side: flat water band, no sprites; landward: palms/scrub, low cliffs | flat sea line, one sun disc | sand/olive scrub; bright blue |
| **farmland** | 1000 | 100–200 | ±1–2.5 | 50–150 | straight 5, sweeper 3, crest 2 | 4, slow (tractor-heavy) | tractor, tree-stump | fence posts, barns (rare), tree rows, silos | flat, distant tree line | green/gold fields; pale blue |
| **highway** | 1400 | 150–300 | ±0.5–2 | 50–200 | straight 6, sweeper 4, rest-stop 1 (landmark) | 14, fast | barrier (roadworks), cone | guardrail poles dense, billboards, overpass (landmark), rest-stop sign+lot | low hills | grey-green; hazy blue |
| **strip** | 1200 | 60–120 | ±1–3 | 0–50 | straight 4, sweeper 2, lot-entrance 2 | 12, medium, sedan-heavy | cone, parked sedan (new) | big box blocks, signs on poles, parking lots (wide flat coloured bands), strip mall rows | low, flat, signs | asphalt grey lots; washed sky |
| **small-town** | 900 | 40–80 | ±2–4, short | 0–100 | main-street 3, corner 3, straight 2 | 6, slow | parked sedan, cone | 1–2 storey blocks close to road, trees, a church/water tower (landmark) | low roofs | grey road, green verges; warm sky |
| **city** | 1000 | 30–70 | ±3–6, short, 90°-feel | 0–50 | corner 4, straight 3, esses 1, bridge 1 | 16, slow | parked sedan, barrier | tall blocks with window dots both sides, dense; occasional plaza gap | skyline blocks, lit windows at dusk/night | dark asphalt; sky by time of day |
| **foothills** | 950 | 50–100 | ±2–4 | 200–400, climbing bias | sweeper 4, crest 3, esses 2 | 5, medium | rock, tree-stump | conifers increasing with altitude, boulders | rising ridge line | green → brown; clear |
| **mountains** | 800 | 20–60 | ±4–6, switchbacks | 300–600, alternating | switchback 5, hairpin 3, crest 2, tunnel-mouth 1 (landmark) | 3, slow (truck) | rock | sparse conifers, rock walls one side, drop-off the other (no sprites, darker ground band) | jagged peaks, snow caps | grey rock; deep blue, dusk purple |
| **valley** | 1000 | 100–180 | ±1–2.5 | -300–-100 first third (descent), then 0–100 | descent 3, straight 4, sweeper 2 | 5, medium | tree-stump | orchards/fields, farmhouses, both walls of the valley as horizon | ridge on both sides, near | green; bright |
| **river** | 900 | 60–120 | ±1.5–3 meander, alternating sign | 0–100 | meander 5, bridge 2 (landmark), straight 2 | 4, slow | rock | one side river band that swaps sides at bridges; willows/reeds | low, tree line | green/blue band; soft sky |
| **lake** | 950 | 80–140 | one long sign held 3–4 stretches (shore curve), then straight | 50–150 | shore-sweeper 5, straight 2, crest 1 | 4, medium | rock, tree-stump | lakeward side: water band with distant far shore silhouette; landward: cabins, pines | far shore ridge reflected as a second dark band | blue; pastel sky |

"Landmark" motifs are rare one-off chunks that make a region memorable: a rest stop, a
bridge, a tunnel mouth, a town's water tower, a coastal lighthouse, a city bridge. They
have a `RARITY` and a per-journey cooldown so they never repeat back to back.

### 4.4 Choosing the next chunk

1. If dwell is not expired: draw a motif from the region's weights, excluding the motif
   of the previous chunk unless the region allows repeats (`highway`, `farmland`).
2. **Library first:** if `chunks/<region>/` has one or more tested chunks with that
   motif, pick one the journey has not used in the last 12 chunks. Apply variation
   operators (below).
3. **Parametric fallback:** otherwise synthesise the motif from the region's parameter
   ranges. The fallback must always exist so the game is infinite with an empty library.
4. Attach obstacles, traffic hints and scenery from the region's sets according to the
   chunk's own hints (a library chunk can say "no obstacles in this hairpin").
5. Validate the chunk in isolation (existing `track.validate` rules) and the join with
   the previous chunk (curve jump ≤ 4, width step ≤ 0, since width changes only via
   `WIDTH` ramps). A failed chunk is discarded and step 1 rerolls with the next random
   draw; the reroll count is logged in telemetry so a bad library chunk is noticed.

**Variation operators** turn a library of dozens into effectively infinite content:

| Operator | What it does | Constraint |
|---|---|---|
| mirror | negate every curve | always allowed unless chunk says `NOMIRROR` (e.g. coast with sea on one side, river bridges) |
| curve-scale | multiply all curves by 0.8–1.25 | stays within region range |
| length-scale | multiply stretch lengths by 0.8–1.3, rounded | stretches never shorter than 10 segments |
| hill-scale | multiply hills by 0.7–1.3 | region amplitude |
| offset-reroll | re-draw obstacle/traffic lateral offsets | ±0.15 of authored value |
| thin | drop each obstacle with p=0.3 | never adds |

### 4.5 Continuity guarantees

- Curve: every stretch starts at 0 and ends at ≤ 0.02 (already true). Chunk boundaries
  are stretch boundaries. Nothing else needed.
- Height: `y` is carried across chunks as generator state. Long-run drift is bounded by
  giving every region a target altitude band and biasing `hill` toward it (mountains
  high, coast/lake at 0). This is the only place the chain looks at absolute `y`.
- Width: a change between regions is emitted as a `WIDTH` ramp over the transition
  chunk (linear over ≥ 40 segments). Per-segment width is already supported by the
  renderer; the loader just has to write it.
- Colour: the transition chunk carries per-segment `blend` in 0..1; the renderer lerps
  the blend step selects one of the pre-built transition palettes for that band (§5.3);
  ground, rumble, road and haze all follow because they are palette entries.
- Scenery density: transition chunk lerps the density of the outgoing and incoming
  sprite sets by the same `blend`.

### 4.6 The parametric fallback, concretely

Per motif, a tiny recipe in terms of `ROAD` lines. Examples:

```
straight     : ROAD L 0 h              L in region straight range, h ~ hill noise
sweeper      : ROAD L/4 0 0 ; ROAD L c h ; ROAD L/4 0 0
esses        : ROAD L c 0 ; ROAD L -c 0 ; ROAD L c*0.8 0
hairpin      : ROAD 40 0 0 (braking zone) ; ROAD 30 5..6 0 ; ROAD 30 0 0
switchback   : hairpin ; ROAD 25 0 +300 ; mirrored hairpin ; ROAD 25 0 +300
crest        : ROAD L 0 +h ; ROAD L*0.5 0 -h*0.3
descent      : ROAD L c*0.5 -h ; ROAD L -c*0.5 -h
meander      : alternate sign sweepers of random length, c in 1.5..3
main-street  : ROAD 30 0 0 ; corner ; ROAD 60 0 0 (buildings dense) ; corner
corner       : ROAD 15 0 0 ; ROAD 12 6 0 ; ROAD 15 0 0
bridge       : WIDTH ramp -150 ; ROAD 60 0 0 (rails both sides, water band) ; WIDTH ramp back
rest-stop    : ROAD 80 0 0 with shoulder widened one side + sign + lot sprites
```

Hill noise: a 1-D value-noise function of absolute segment index seeded from the journey
seed, scaled by region amplitude, so terrain has continuity across chunk boundaries that
the motif recipes alone would not give.

## 5. Runtime: the segment window

### 5.1 Data structure

```
window = {
  'base': 0,            # absolute index of segments[0]
  'segments': [],       # dicts: curve, y, width, region, blend, scenery list
  'obstacles': [],      # (abs_seg, offset, kind, hit_flag)
  'traffic': [],        # live cars: [abs_z, offset, speed, kind, cooldown]
  'chunk_log': [],      # (abs_seg_start, region, chunk_id) for telemetry/journey log
}
```

- `segment_at(window, z)` → `segments[int(z/SEGMENT_LENGTH) - base]`.
- Every frame, after moving the player: if `len(segments) - (player_seg - base) <
  DRAW_DISTANCE + LOOKAHEAD` (`LOOKAHEAD` = one max chunk, 450), generate the next chunk
  and append. Drop segments more than 20 behind the player and bump `base`.
- Generating a chunk is a few hundred dict appends; measured cost target ≤ 5 ms on the
  N900. If it measures higher, generate one stretch per frame instead (the chunk is
  planned in one go, expanded lazily). Memory: window ≤ ~1,000 dicts. Trivial.
- Segments carry `heading` (the running sum of curve, what `track.py` today exposes as
  the first difference of `x`) so the backdrop pan works unchanged. No absolute `x`.
- Chunk boundary bookkeeping: `y`, `heading`, current region, dwell counter,
  recent-chunk ring, landmark cooldowns, and the value-noise seed live in a `generator`
  object created once from the journey seed.

### 5.2 Traffic and obstacles

- Obstacles arrive with their chunk, are tested by absolute segment, and are dropped with
  the window. `find_obstacle_hit` is already centreline-relative and only needs to
  index the window instead of `trk['obstacles']`.
- Traffic becomes a spawner: while `len(live cars ahead) < region density`, spawn a car at
  `player_z + (DRAW_DISTANCE + rand(0, 40)) * SEGMENT_LENGTH`, lane offset from the
  region's lane set, speed from the region's speed band. Drop cars more than 10 segments
  behind. Cooldown after a hit as today. Reacting traffic stays out of scope, but the
  spawner is the structure that would host it.
- Density per region is in cars per 1,000 segments, converted to a spawn probability per
  generated segment so it is speed-independent.

### 5.3 Rendering the environment on a 600 MHz CPU

The environment has to change continuously without adding draw calls per frame. The
device charges ~90 µs per pygame call and the shipping frame already spends ~160
polygons and ~90 fills to run at 22–24 fps, so the budget is: **no more than ~40 extra
calls per frame at any region's maximum scenery density, and zero extra calls outside
transitions.** Session 3's `build_palette`, `build_backdrop` and the per-band ground
fills are the hooks; nothing below replaces them.

| Layer | How | Extra draw calls |
|---|---|---|
| Palette | `build_palette` today blends one theme's colours over every distance at startup. Build one palette per region at startup (11 palettes, ~1,000 `_blend` calls each, a few ms total). Each band indexes `palette[segment.region][i]`, so a boundary crossing between regions costs nothing. | 0 |
| Transition palettes | When a transition chunk is generated, build 4 intermediate palettes between the outgoing and incoming region (lazily, once, ~4× a startup palette). Transition segments carry a `blend` step 0..4 that picks one. Colour then steps in 5 stages across the chunk instead of lerping per frame, which is invisible at 22 fps and free. | 0 |
| Sky | One `build_theme_background` surface per region at startup (11 × 800×480 × 2 bytes ≈ 8.4 MB; acceptable in 245 MB, or halve it by storing only the top 55% rows that the gradient actually uses). During a transition, blit the incoming sky over the outgoing with `set_alpha` stepped with `blend`. | +1 blit during transitions |
| Horizon backdrop | `build_backdrop` already generates ridges or a lit skyline per theme with `_Rng`. Add generators per region (sea line + sun, tree line, peaks with snow, big-box roofline, far lake shore, valley walls both sides). One 800×96 strip per region at startup. Parallax pan unchanged. Transition: two backdrop blits with `set_alpha` on the incoming one, stepped with `blend`. | +1 blit during transitions |
| Ground and road | Already per-band fills and polygons; the colour comes from the region palette above. Road surface colour per region (asphalt, concrete, dirt) is a palette entry, not a new call. | 0 |
| Water | A coast, river or lake side is a **per-band colour choice**, not a sprite: the ground fill is full-width, so draw the water as one extra polygon per band on that side only for bands that are wide enough to matter (`nw > 10`). At most ~25 visible wide bands. | ≤ 25 on water sides |
| Roadside sprites | Extend `draw_sprite` with primitive recipes: tree = 2 calls (trunk rect, canopy polygon); building = 1 rect + at most 4 window-row rects; sign = pole + rect; guardrail = the existing poles at interval 2. Hard per-frame sprite budget of **40 calls**, nearest first; farther scenery is simply not drawn, which the depth haze already excuses. | ≤ 40 |
| Time of day | A tint multiplies region colours before palettes are built; region × time-of-day palettes are built lazily and cached (at most 44). | 0 |

`tools/racer_fps.py` gains `--region` and `--density` arguments and a "transition
stress" mode that forces a transition every 2 s, so this table gets device numbers before
any of it ships. `tools/render_shot.py` gets `--journey SEED --at SEGMENT` so every
region's look can be checked in a PNG on the laptop first.

### 5.4 Interface changes to `game.py`

- `main()` takes `--journey [seed]` or a `.trk` path. The desktop launcher script passes
  `--journey`. Finite tracks are loaded through the same window API (a `.trk` is just a
  journey with one hand-written chunk list and a finish), which removes the need for two
  render paths.
- `draw_road` reads from the window instead of `trk['segments']`, indexing by
  `idx - base`. Its per-frame curve accumulation and backdrop pan stay as they are; the
  pan reads the base segment's `heading` instead of differencing `x`.
- The `finish` outcome is only possible for `.trk` runs. Journeys end on `quit`,
  renamed `stop` in the `RESULT` line to stop implying a bug.
- `RESULT` gains `seed=`, `distance=` (segments), `regions=coast,small-town,farmland,…`.
- A small HUD: odometer (distance in "miles", 1 mile = 1,000 segments to keep the number
  human-sized) and the current region name, fading in for 2 s at each region change.

## 6. File formats

### 6.1 Chunk files: `chunks/<region>/NNN-<name>.chk`

Same rules as `.trk`: plain text, one directive per line, `str.split()` parsing, unknown
directives ignored, `#` comments. Segment indices are local to the chunk.

```
NAME Switchback pair
REGION mountains
MOTIF switchback
RARITY 1                      # 1 common .. 5 rare (landmarks)
TAGS climb narrow             # free-form, for curation queries
NOMIRROR                      # optional: asymmetric scenery, do not mirror
ROAD 40 0 0
ROAD 30 6 0
ROAD 25 0 300
ROAD 30 -6 0
ROAD 25 0 300
ROAD 40 0 0
OBSTACLE 5 0.6 rock
SCENERY 0 190 left rockwall   # from-seg to-seg side kind: overrides region default density
SCENERY 0 190 right dropoff
TRAFFIC 2 -0.5 200 truck      # a hint: a car spawned with the chunk; the spawner adds more
```

`WIDTH` inside a chunk is not allowed; width is a region property and changes only in
transitions. `HILL` is expressed through `ROAD` as today.

Validation of a chunk = `track.validate` rules + region range checks (curve within the
region's range, hill within amplitude, length within 150–450) + a **drive simulation**:
a scripted bot with a simple look-ahead steering rule must complete the chunk at ≥ 70%
of `MAX_SPEED` average without touching grass, using the real physics constants from
`game.py`. A chunk that cannot be driven by the reference bot is rejected before a human
ever sees it. The sim runs on the laptop under Python 3 with `tools/fake_pygame.py`
shadowing pygame, the way `render_shot.py` already does, so it can also write a PNG of
the moment the bot left the road. To keep the sim and the device honest with each other,
lift the physics block of `game.main()` (zone checks, acceleration, centrifugal drift,
collisions) into a `physics.py` module that both call; today that block is inline in
the frame loop and the sim would otherwise have to copy it.

### 6.2 Region table: `regions.py`

A data-only Python module (dicts and tuples, no logic) holding §4.2 and §4.3. It is game
design, not model output, so it does not need to be a text format. If a later session
wants the model to propose regions, the same table can be serialised to a `.rgn` text
format under the same parsing rules; do not build that until it is needed.

### 6.3 Backward compatibility and export

- `tracks/*.trk` load unchanged.
- `tools/journey_export.py --seed N --chunks 6 --out tracks/9xx-seed-N.trk` writes the
  first N chunks of a journey as a finite `.trk` (region tags dropped, `FINISH` at the
  end). This lets the existing validator, `test_track.py`, bot runs and `racer_fps.py`
  exercise generated road with no new tooling, and gives the "few good tested examples"
  a concrete home: a journey slice that a human drove and liked is exported and kept.

## 7. The model's role: offline curation, not runtime generation

The research question is whether a model on a cloud node can design content for a device
it will never run on. The infinite road sharpens it: the model no longer designs a track,
it designs **the categories** the generator draws from.

### 7.1 Seed library

Goal for the first pass: ~3 chunks per region × 11 regions ≈ 33 chunks, half hand-written
(to set the bar and establish the category), half from `qwen3-coder`. Target after
curation: 60+ chunks, at least 2 landmark chunks per region.

`tools/generate_chunk.py --region mountains --motif switchback --count 4` builds a prompt
from `chunks/FORMAT.md`, the region's row of §4.3 in prose ("narrow, 20–60 segment
straights, curves ±4–6, big alternating hills, sparse conifers, rock wall one side") and
2 exemplar chunks of the same region as few-shot examples, then validates each candidate
with the static checks and the drive simulation and writes only passers to
`chunks/<region>/candidates/`. Same 900 s timeout budget as `generate_track.py`. Compare
`qwen3-coder`, `qwen2.5-coder:7b` and `kimi-k2.7-code` on pass rate and on the curation
metrics below, which is the HANDOFF's item 6 done with a sharper yardstick.

### 7.2 Curation loop

1. `game.py --chunk chunks/mountains/candidates/003-x.chk` loops one chunk with the
   region's palette so a human can drive it repeatedly on the device.
2. Telemetry (§8) tags every sample with `chunk_id`, so `tools/curate.py` can print per
   chunk: average speed fraction, grass time %, hits, rerolls, and the human's one-word
   verdict typed after the run.
3. Promote by moving the file from `candidates/` to the region directory. Demote by
   deleting. The library is the test suite.

## 8. Telemetry and scoring

- New telemetry columns: `region`, `chunk_id`, `blend`. The 10 Hz sample rate stays.
- Summary line adds `seed`, `distance`, `regions`, `chunks`, `rerolls`.
- End-of-run journey log printed to stdout and shown on screen for 3 s before quit:
  `41 mi · coast → Harbour town → farmland → highway → strip → city · 3 hits`.
- Score for now is distance. The handoff's open question about fun is bigger than
  scoring; see §11 for the two candidate stake mechanics rather than deciding here.

## 9. Testing

| Test | Where | What it asserts |
|---|---|---|
| `test_journey.py` | on laptop, Python 3 and 2.5 | For 500 seeds × 300 chunks: no curve jump > 4, no width step, `y` within global bounds, every region visited at least once across the seed set, dwell within bounds, no A→B→A except allowed, landmark cooldowns respected, generation is deterministic (run twice, compare) |
| `test_chunks.py` | on laptop | Every file under `chunks/` (not `candidates/`) passes static validation and the drive simulation |
| `tools/journey_dump.py --seed N --chunks 40` | on laptop | Prints the region sequence and per-chunk motif/length/max-curve as a table; the human-readable smoke test |
| `tools/render_shot.py --journey N --at S` | on laptop | A PNG of any point on any journey through `fake_pygame`; every region and every transition gets looked at before it is carried to the device |
| `tools/racer_fps.py --journey --seed N` | on device | Worst second no lower than the session 3 baseline (25.5 fps render probe, ~22 fps full loop) with scenery at each region's maximum density and transitions every 2 s |
| Bot journey | on device | `game.py --journey 1 /tmp/tilt telemetry/bot.csv 120` with `bot_steer.py`: runs 120 s without a traceback, window never starves (a starve is logged as an event) |
| Human drive | on device | The only test that matters. Journey log and telemetry saved per run |

## 10. Phases

Each phase ends with a human drive on the device. Nothing advances on bot evidence alone;
that is the lesson of session 2.

| Phase | Deliverable | Exit criterion |
|---|---|---|
| **0. Device baseline** | Exactly what HANDOFF's "session 4 must measure first" says: `racer_fps.py` on the device with the session 3 renderer, then a human drive of Autumn Hills. Decide `MAX_SPEED` and a first `CENTRIFUGAL` from that drive; both now have a visible effect. No infinite-road code. | Someone has driven the fixed renderer and written down what a `curve` of 3 and 6 feels like, and the fps floor is known. §4.3's ranges get corrected from that note. |
| **1. Window + parametric road** | `window`, generator object, `regions.py` with 3 regions (farmland, foothills, mountains), parametric motifs only, value-noise hills, odometer, `--journey`, `journey_export.py`, `test_journey.py`. Palette switches hard at boundaries. | 10 minutes of driving with no starvation and no visible kink; a human says the terrain "changes". |
| **2. Regions and blending** | All 11 regions, transition chunks, ground/sky lerp, horizon strips with parallax, traffic spawner, region HUD, `racer_fps.py` stress mode. | Every region is recognisable when named blind by the driver; fps floor holds. |
| **3. Chunk library + model** | `chunks/FORMAT.md`, chunk loader, variation operators, drive simulation, `generate_chunk.py`, `--chunk` loop mode, `curate.py`, 33-chunk seed library. | Library chunks are chosen over parametric ones at least 60% of the time in `journey_dump`; curation table exists for every chunk. |
| **4. Scenery and landmarks** | Sprite recipes per region, water bands, buildings, signs, rest stop / bridge / tunnel-mouth / water-tower / lighthouse landmarks, sprite budget. | fps floor holds at max density; landmarks show up in journey logs. |
| **5. Polish** | Journey log screen, seed sharing, time of day, telemetry columns, README/HANDOFF rewrite, project card status update. | A stranger can pick it up, drive, and tell you where they went. |

Phase 0 is small and must come first; it is the handoff's own next step, not this
spec's. Phases 1 and 2 are the core. Phase 3 is where the model comes back in, and it is
deliberately after the parametric road works, so the library is an improvement on a
playable baseline rather than a dependency. Carrying any phase to the device is
`sh tools/deploy.sh`; the desktop launcher does not need reinstalling unless `desktop/`
changes.

## 11. Decisions for the user

1. **Stakes.** A pure road trip with no fail state may be pleasant but not tense. Two
   cheap options that fit the arcade lineage: (a) OutRun-style time extension at region
   boundaries, run ends at 0; (b) fuel that drains with distance and refills at rest
   stops and towns, which also makes the highway/town regions matter mechanically. This
   spec keeps the pure road trip for Phases 0–4 and leaves the choice for Phase 5.
2. **Region set.** §4.3 has 11. Cutting `strip` and `river` into landmarks inside
   `highway` and `valley` would drop the count to 9 with less palette work. Keep all 11
   if the "strip malls" and "along rivers" images matter as much as the brief suggests.
3. **Time of day.** Cheap to add as a tint (§5.3) but it multiplies the palettes to test.
   Recommend Phase 5, not earlier.
4. **Daily seed.** Same journey for everyone on a given date, so playtests are
   comparable. Trivial to add; decide whether the default seed is the clock or the date.
5. **Repo visibility.** Unchanged from HANDOFF item 7, but the chunk library is exactly
   the kind of artefact the class showcase would want to see.

## 12. Non-goals

- No image assets. Everything stays primitives, so the model can describe scenery in
  text and the device has nothing to load.
- No runtime model calls, no network on the device.
- No traffic AI beyond spawn/despawn/cooldown.
- No branching roads or junctions; the road is one ribbon. Intersections in towns and
  cities are suggested by cross-stripes and building gaps, not driven.
- No save state. A journey is one sitting.
