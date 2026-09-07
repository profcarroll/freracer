# freracer track file format (.trk)

Plain text, one directive per line. No JSON, no nesting. Parsed with `str.split()` only.
Blank lines and lines starting with `#` are ignored. Order of directives does not matter
except that `ROAD` directives are concatenated in file order to build the route.

A track is a ribbon of road built from a sequence of `ROAD` stretches. Each stretch adds a
run of fixed-length segments (100 world units each) that curve and/or climb, eased in and
out smoothly so the road never kinks. This mirrors the classic pseudo-3D racer technique
(Pole Position / OutRun-style scanline projection): the renderer only needs curve and
elevation per segment, not pixel geometry.

Directives:

    NAME <text>                       rest of line is the track's display name
    THEME <keyword>                   scenery palette, e.g. autumn-hills, dusk-city, coast
    SEED <int>                        used to seed scenery/decoration placement (trees etc.)
    PAR <seconds>                     target lap time
    WIDTH <units>                     road half-width in world units (default 1000)
    ROAD <segments> <curve> <hill>    add a stretch: segments = length in 100-unit steps,
                                       curve = signed curvature strength (0 = straight,
                                       positive = bends right, negative = bends left,
                                       typical range -6..6), hill = total height change in
                                       world units over the stretch (positive = climbs),
                                       eased in/out over the stretch so joins are smooth.
    OBSTACLE <segment> <offset> <type>   a static hazard. segment = index counting from 0
                                          along the ROAD sequence. offset = lane position,
                                          -1.0 (left edge) .. 1.0 (right edge), 0 = centre.
                                          type = rock | cone | barrier | tree-stump
    TRAFFIC <segment> <offset> <speed> <type>   an AI car that loops the lap at a roughly
                                          constant speed (world units/sec, positive =
                                          same direction as the player). type = sedan |
                                          truck | tractor.
    FINISH <segment>                  optional: marks the lap boundary at this segment
                                          index instead of the end of the last ROAD. Omit
                                          for a track that is one lap end-to-end.

Unknown directives are ignored on purpose (forward compatible).

## Worked example

    NAME Autumn Hills
    THEME autumn-hills
    SEED 1
    PAR 75
    WIDTH 1000
    ROAD 40 0 0
    ROAD 60 3 0
    ROAD 30 0 400
    ROAD 50 -4 -200
    ROAD 40 0 -200
    OBSTACLE 55 -0.4 cone
    OBSTACLE 130 0.6 rock
    TRAFFIC 20 -0.5 260 sedan
    TRAFFIC 90 0.5 220 truck

This is a short lap: a straight, a right sweeper, a climb, a longer left hairpin-ish bend
descending, then a straight back down, with two static hazards and two AI cars.

## Why this shape

An LLM asked for a whole track as raw per-segment geometry drifts and produces kinks
(curve/height discontinuities the renderer cannot smooth). Asking for a short list of
`ROAD` stretches — the same vocabulary a person would use to describe a course out loud
("long right sweeper, then it climbs, then a tight left down the hill") — keeps the output
short, keeps every join continuous by construction (the loader eases each stretch), and
still gives the model real control over pacing and difficulty.
