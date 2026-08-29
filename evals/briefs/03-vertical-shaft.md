# Level Brief — "The Shaft", a vertical climb

**The stress case for reachability.** Almost every jump is near the limit, so
the Level Designer and Player Controller have to actually agree on numbers
rather than each assuming defaults.

## Required beats
1. Spawn at the bottom of a narrow vertical shaft.
2. **Seven** ascending ledges, alternating left and right walls.
3. At least three of them narrow enough (≤ 80px) to demand a precise landing.
4. Two collectibles, both requiring a deliberate detour off the climb.
5. The exit at the very top.

## Feel
Heavy and deliberate. A missed jump should cost real height. Coyote time and
jump buffering are mandatory — without them this is unfair rather than hard.

## Constraints
- Single screen: 1152 x 648, used mostly vertically. Player is 32 x 48.
- Nothing may require a jump within 10% of the controller's actual limits.
  If the geometry needs more height than the default tuning gives, retune the
  controller and say so — do not silently ship an impossible jump.
