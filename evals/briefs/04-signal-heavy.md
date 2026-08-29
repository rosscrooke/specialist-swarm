# Level Brief — "Pressure", a switch-and-door room

**The stress case for the .tscn format.** This brief deliberately demands the
constructs that are easiest to get wrong when writing scene files by hand:
many sub-resources, deep node nesting, and signal connections between
siblings.

## Required beats
1. Ground, plus three platforms at different heights.
2. **Three pressure plates** (Area2D) on separate platforms.
3. **One door** (a StaticBody2D that moves aside) which opens only when all
   three plates have been touched at least once.
4. The exit behind the door.
5. Two collectibles, one of them behind the door.

## Feel
Puzzle-ish rather than twitchy. Movement can be forgiving.

## Constraints
- Single screen: 1152 x 648. Player is 32 x 48.
- Every plate must signal the door. Wire them with real `[connection]` blocks
  or explicit `connect()` calls in `_ready` — state which you used and why.
- Each plate and the door needs its own collision shape. Do not share a
  sub_resource between nodes of different sizes.
