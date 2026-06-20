---
name: buddy-match-playbook
description: BTS-Synthetic onboarding buddy matching method. Use whenever picking an onboarding buddy or mentor for a new hire from a candidate roster — covers eligibility filters, how to weight team and seniority, tiebreakers, and the required output format. Trigger on any request to match a buddy, assign an onboarding buddy, pick a mentor for a new hire, or recommend a buddy from a roster.
---

# Buddy Match Playbook

You are matching ONE new hire to the best available buddy from a candidate roster.
A buddy is a **peer mentor** for the hire's first month — close enough to the work to
unblock them daily, senior enough to know how things actually run. Work the steps in
order: filter first, then score on the primary signals, then break ties.

## Seniority ladder

`IC1` Junior → `IC2` → `IC3` Senior → `IC4` Staff → `IC5` Principal.
Manager track: `M1` (front-line manager), `M2` (manager-of-managers), which sit
alongside IC4/IC5 for seniority comparison. Map each level to its index (IC1 = 1,
IC2 = 2, … IC5 = 5; treat M1 ≈ 4, M2 ≈ 5) when you compare seniority.

## Step 1 — Hard eligibility filters

Drop any candidate that fails ANY of these. They are out — do not score them.

1. **Capacity.** `active_buddy_count < max_buddy_capacity`. A candidate already at
   their ceiling is excluded even if they're a perfect fit. *(reason: capacity)*
2. **Availability.** The candidate must NOT be on leave during the hire's first two
   weeks. If `on_leave_until` is set and falls on or after the hire's start date, they
   are unavailable for the critical settling-in window. *(reason: leave)*
3. **Seniority floor.** Buddy level ≥ hire level, **OR** equal level with
   `tenure_months ≥ 12`. A buddy more junior than the hire is excluded.
   *(reason: too-junior)*
4. **Not the hire's manager.** The hire's direct manager is never the buddy — the
   buddy is a peer, not the reporting line. If the only strong same-team option is the
   manager, exclude them and raise a flag. *(reason: is-manager)*

## Step 2 — Primary scoring (the headline signals)

Score every surviving candidate on **team** and **seniority** first. These dominate.

**Team match:**
- Same team as the hire → best.
- Adjacent / sibling team (works closely day-to-day, e.g. Analytics Engineering next
  to Data Platform Engineering) → good.
- Unrelated team → weak; only acceptable when nothing closer survives.
- A non-engineering function buddying an engineer ranks below any engineering team.

**Seniority fit:**
- Exactly **one level above** the hire → ideal (knows the ropes, still close to the work).
- Same level (tenured ≥ 12mo) or **two levels above** → acceptable.
- Very large gaps (e.g. Principal buddying a Junior) → score lower; too distant for
  daily rapport.

Pick the candidate(s) that lead on team first, then seniority fit. Only if two
candidates are close on both do you go to Step 3.

## Step 3 — Secondary tiebreakers (only to break near-ties)

Apply in roughly this order, never to override a clear Step 2 winner:
1. **Timezone overlap** — same/adjacent timezone beats a large offset.
2. **Shared language** — a common working language helps.
3. **Shared interests** — a point of personal connection.
4. **Prior buddy rating** — higher is better evidence they mentor well.
5. **Lower current load** — fewer active buddies = more attention to give.

## Step 4 — Output format

Produce exactly this structure:

```
RECOMMENDED BUDDY: <name> (<title>, <team>, <level>)
Why: <2–4 sentences naming the signals that drove it — lead with team and seniority,
then the tiebreakers that sealed it.>

BACKUP BUDDY: <name> — <one line on why they're the runner-up.>

EXCLUDED (filtered in Step 1):
- <name> — capacity
- <name> — leave
- <name> — too-junior
- <name> — is-manager

FLAG (if any): <e.g. "No same-team peer had capacity — recommended an adjacent-team
buddy" or "The hire's manager is the most senior same-team option but was excluded as
the buddy must be a peer." Omit this line if there's nothing to flag.>
```

Be decisive — recommend one buddy, not a shortlist. Name the specific data points
(team, level, timezone, interest) you relied on so the Onboarding Lead can trust it.
