# Level Brief — "Crystal Caverns", Level 1-3

**Project:** Crystal Caverns, a 2D precision platformer
**Level:** 1-3 — the first level that asks the player to think
**Target:** ~40 seconds for a competent player, first-try clearable

## The fantasy

An abandoned mining shaft, lit from below by crystal seams. Cool blues and
slate greys, with the crystals as the only warm colour on screen. The player
is descending into somewhere that used to be worked and is not any more.

## Required beats, in order

1. **A safe opening.** Flat ground, room to test the controls before anything
   can go wrong. The player should be able to run and jump for two seconds
   without consequence.
2. **A taught jump.** One gap wide enough to require a committed jump but
   narrow enough that a mistimed one still lands. This is the level teaching
   its own vocabulary.
3. **A rising sequence.** Three ascending ledges, each reachable from the last.
   The middle one should be the narrowest platform in the level.
4. **A decision.** A point where a visible crystal sits off the critical path,
   reachable but costing a riskier jump. The player chooses greed or safety.
5. **The exit.** On the highest platform, clearly visible from at least two
   platforms earlier so the player can see where they are going.

## Contents

- **3 crystals** to collect. One on the main path, one on the risky detour,
  one that is simply a reward for looking up.
- **No enemies.** This level is about traversal.
- **No hazards** on the critical path. The risk is missing a jump, not dying
  to something.

## Feel

Grounded, not floaty. The player should feel heavy enough that a jump is a
commitment, but responsive enough that a missed landing is clearly their own
fault. Coyote time and jump buffering are expected — this is a precision
platformer and it has to be fair.

## Constraints

- Single screen: 1152 x 648. The camera should barely need to move.
- Nothing above y = 120 — the top of the screen stays empty for atmosphere.
- The player is 32 x 48.
