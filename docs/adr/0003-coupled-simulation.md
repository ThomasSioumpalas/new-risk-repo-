# ADR 0003: Coupled simulation with named random streams

**Status:** Accepted

## Context
The key decisions compare control states: inherent against current, treatment
option A against option B, and "what if control X fails". Differences between
independent Monte Carlo runs are noisy, and an option's benefit can drown in
simulation error. Results must also be reproducible, and adding an option must
not reshuffle the others.

## Decision
Simulate the inherent loss events once and evaluate every control state on the
same events by **Poisson thinning** (keep an event if `V < m`), sharing all
random numbers (common random numbers). Each input has its own random stream,
derived from `SHA-256(scenario/input)` and the seed.

## Consequences
* Paired differences are several times more precise. Both standard errors
  are reported to make this visible.
* Monotonicity holds exactly per trial (a control never increases loss) and is
  checked by a property-based test.
* All states share the inherent event count, so the memory cost scales with
  inherent frequency. An event budget guards against excessive allocation.
