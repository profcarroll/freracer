# regions.py - the country the infinite road drives through. Data only.
# Python 2.5 safe: dicts and tuples, no logic. See docs/INFINITE-ROAD-SPEC.md
# section 4 for what each field means and where the numbers come from.
#
# Phase 1 builds three regions. The successor table below is the full
# eleven-region chain from the spec so it does not have to be rewritten as
# regions are added; journey.py collapses any successor that is not yet in
# REGIONS onto STAND_IN.
#
# Every range here is a starting point. The curve ranges in particular were
# written before anyone had driven the fixed renderer (spec section 2.1):
# `curve` is angular acceleration, so a long stretch at 3 bends much harder
# than a short one. Expect them to come down once someone has felt them.

REGIONS = {
    'farmland': {
        'width': 1000.0,
        'straight': (100, 200),       # segments, for straight and sweeper motifs
        'curve': (1.0, 2.5),          # magnitude range; sign is rolled
        'hill': (50.0, 150.0),        # units per stretch a motif may add
        'altitude': (0.0, 400.0),     # band the terrain noise wanders in
        'motifs': (('straight', 5), ('sweeper', 3), ('crest', 2)),
        'repeat_motif': 1,            # same motif twice running is fine here
        'dwell': (6, 10),             # chunks before the chain moves on
        'obstacles': ('tree-stump',),
        'obstacle_rate': 3,           # per 1000 segments, straights only
        'colors': {
            'sky': (150, 196, 240),
            'sky2': (216, 230, 242),
            'grass': (118, 150, 52),
            'grass2': (166, 150, 62),
        },
    },
    'foothills': {
        'width': 950.0,
        'straight': (50, 100),
        'curve': (2.0, 4.0),
        'hill': (200.0, 400.0),
        'altitude': (600.0, 1500.0),
        'motifs': (('sweeper', 4), ('crest', 3), ('esses', 2)),
        'repeat_motif': 0,
        'dwell': (5, 8),
        'obstacles': ('rock', 'tree-stump'),
        'obstacle_rate': 5,
        'colors': {
            'sky': (112, 172, 236),
            'sky2': (200, 216, 234),
            'grass': (96, 124, 56),
            'grass2': (136, 112, 64),
        },
    },
    'mountains': {
        'width': 800.0,
        'straight': (20, 60),
        'curve': (4.0, 6.0),
        'hill': (300.0, 600.0),
        'altitude': (1800.0, 3200.0),
        'motifs': (('switchback', 5), ('hairpin', 3), ('crest', 2)),
        'repeat_motif': 0,
        'dwell': (6, 10),
        'obstacles': ('rock',),
        'obstacle_rate': 6,
        # Rock, not grey: the road is a dark neutral grey and session 2
        # learned that ground within a few luminance steps of it vanishes on
        # the outdoor LCD. Warm and clearly lighter.
        'colors': {
            'sky': (62, 112, 204),
            'sky2': (172, 196, 230),
            'grass': (146, 136, 122),
            'grass2': (118, 108, 98),
        },
    },
}

# Weighted successors, spec section 4.2. Order matters: draws walk the tuple.
SUCCESSORS = {
    'coast': (('farmland', 3), ('small-town', 3), ('highway', 2), ('foothills', 1)),
    'farmland': (('small-town', 3), ('highway', 3), ('river', 2), ('foothills', 2), ('lake', 1)),
    'highway': (('strip', 3), ('city', 2), ('farmland', 2), ('valley', 1), ('mountains', 1)),
    'strip': (('city', 3), ('highway', 2), ('small-town', 1)),
    'city': (('highway', 3), ('strip', 2), ('river', 2)),
    'small-town': (('farmland', 3), ('river', 2), ('lake', 2), ('highway', 2), ('coast', 1)),
    'foothills': (('mountains', 4), ('valley', 2), ('lake', 1)),
    'mountains': (('valley', 4), ('foothills', 2), ('lake', 1)),
    'valley': (('river', 3), ('farmland', 3), ('small-town', 2), ('foothills', 1)),
    'river': (('small-town', 3), ('valley', 2), ('farmland', 2), ('city', 1)),
    'lake': (('small-town', 3), ('foothills', 2), ('farmland', 2), ('coast', 1)),
}

# The gentlest places to start a drive.
OPENERS = ('coast', 'farmland', 'small-town', 'highway')

# A -> B -> A is allowed only when A is one of these: they are the country's
# connective tissue and are meant to recur.
RECURRING = ('highway', 'farmland')

# A successor that has not been built yet becomes this. Farmland is the one
# region everything in the full chain passes through anyway.
STAND_IN = 'farmland'

# Regions visited this recently have their successor weight halved.
VARIETY_WINDOW = 4

# Global altitude bounds any journey must stay inside (test_journey.py).
ALTITUDE_MIN = -1000.0
ALTITUDE_MAX = 8000.0
