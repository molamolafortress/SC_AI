# Zerg rules of thumb (fixed prompt prefix; keep stable, no timestamps)

## Tech tree (what requires what)
- spawning_pool -> zergling, sunken_colony, metabolic_boost, lair, hydralisk_den
- hydralisk_den -> hydralisk, grooved_spines, muscular_augments, (lair) lurker_aspect -> lurker
- lair -> spire -> mutalisk, scourge; lair -> queens_nest -> hive
- hive -> ultralisk_cavern, defiler_mound, greater_spire, adrenal_glands
- evolution_chamber -> spore_colony, melee/missile/carapace upgrades
- All production comes from larva (3 per hatchery, +1 every ~14 s). Drones are the economy; each hatchery also adds larva.

## Timings (reference, game time)
- 12 hatch / 11 pool: pool finishes ~2:10, first lings ~2:35. Safe vs 1-rax, risky vs 8-rax/proxy.
- 9 pool speed: lings ~1:55, speed ~3:30. Good vs greedy openings and 2-gate.
- Overpool: lings ~2:15, hatch after. Balanced.
- Terran 2-rax no gas seen before 2:30 -> marine push around 4:30-5:30; needs 1 sunken + lings.
- Terran factory ~4:00 -> vultures/tanks; expect mines; hydra/lurker or muta timing.
- Protoss 2-gate seen <2:30 -> zealot pressure ~3:00; overpool or 9 pool needed. Forge FE -> can go 3 hatch greedy.
- Zerg mirror: pool timing decides; 9 pool vs 12 hatch is dangerous for the hatch player.

## Policy guidance
- Drones first unless a threat is scouted; 2 hatch before pool is greedy, 3 hatch needs safety.
- Change plan only on new information (new enemy building, lost engagement, tech spotted). Repeated flip-flops lose games.
- Never request wall/positions that the map knowledge does not define.

## Economy and static defense (learned from the first A/B, 2026-10-01)
- A sunken or spore colony consumes a drone (plus 50 minerals / 75 minerals). Every static defense request is one fewer worker.
- In ZvZ muta wars the mutalisk count and drone count decide the game; static defense only buys time. Request a spore only
  when enemy mutas are confirmed or a spire is seen finishing before ours, and keep it to 1 unless you are already behind.
- Do not keep stance=defensive for the whole game. Defensive holds the entire army at home; use it for a specific window
  (expected timing push) and return to neutral afterwards so the body can trade and expand.
- expand_policy=never is for an all-in or an imminent attack only. Repeated "never" starves the economy.
- When the execution report shows a request was not applied (e.g. unit_mix drones ignored), do not repeat it; change the lever.
