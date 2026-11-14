## src/hospitalos/decision_support/resources.py L29–L61

```python
0029 def lending_violations(
0030     options: tuple[ReinforcementOption, ...] | list[ReinforcementOption],
0031 ) -> list[str]:
0032     """F02: cumulative check of loans taken from the same unit, skill and hour.
0033 
0034     Each option may respect the lender's minimum on its own; together they must too. When
0035     options of one lender declare different staffing figures, the most conservative pair is
0036     used (lowest scheduled, highest minimum).
0037     """
0038     per_hour: dict[tuple[str, str, datetime], list[ReinforcementOption]] = {}
0039     problems = []
0040     for o in options:
0041         if o.source != "shared_unit":
0042             continue
0043         if o.lending_unit is None:  # V4-R02
0044             problems.append(f"lending_unit_unknown:{o.option_id}")
0045             continue
0046         for h in touched_hours(o.start, o.end):  # V4-R01: common grid
0047             per_hour.setdefault((o.lending_unit, o.skill, h), []).append(o)
0048     for (unit, skill, h), taken in sorted(per_hour.items()):
0049         scheduled = [o.lending_unit_scheduled for o in taken]
0050         minimum = [o.lending_unit_minimum for o in taken]
0051         if any(v is None for v in scheduled + minimum):
0052             problems.append(f"lending_unit_commitment_unknown:{unit}:{skill}:{h.isoformat()}")
0053             continue
0054         sched, mini = min(scheduled), max(minimum)  # type: ignore[type-var]
0055         if sched - len(taken) < mini:  # type: ignore[operator]
0056             ids = "+".join(sorted(o.option_id for o in taken))
0057             problems.append(
0058                 f"lending_unit_minimum_cumulative:{unit}:{skill}:{h.isoformat()}:"
0059                 f"{sched}-{len(taken)}<{mini}:{ids}"
0060             )
0061     return problems
```

## src/hospitalos/decision_support/resources.py L202–L255

```python
0202     def reserve_all(
0203         self, requests: list[tuple[str, str, str, int | None]]
0204     ) -> tuple[bool, list[str]]:
0205         """F03: all-or-nothing. Requests are (resource, slot, key, capacity if known).
0206 
0207         Everything is checked on a staged copy first; the ledger is changed only if every
0208         request succeeds, so a refused plan leaves no new commitment and touches no
0209         reservation held by another request.
0210         """
0211         staged = ResourceLedger(
0212             capacity=dict(self.capacity),
0213             by_key=dict(self.by_key),
0214             used={k: list(v) for k, v in self.used.items()},
0215         )
0216         details = []
0217         ok_all = True
0218         for resource, slot, key, cap in requests:
0219             # V4-R03: the capacity of the CURRENT snapshot replaces any remembered one,
0220             # including when it became unknown. Existing holds are kept, never erased; a
0221             # capacity now below them is traced as a conflict and blocks new holds.
0222             holders = staged.used.get((resource, slot), [])
0223             previous = staged.capacity.get((resource, slot))
0224             staged.capacity[(resource, slot)] = cap
0225             if previous is not None and cap != previous and holders:
0226                 if cap is None:
0227                     self.conflicts.append(
0228                         f"capacity_now_unknown:{resource}@{slot}:holds={len(holders)}"
0229                     )
0230                 elif len(holders) > cap:
0231                     self.conflicts.append(
0232                         f"capacity_below_existing_holds:{resource}@{slot}:"
0233                         f"{len(holders)}>{cap}"
0234                     )
0235             ok, why = staged.reserve(resource, slot, key)
0236             details.append(f"{resource}@{slot}:{why}")
0237             ok_all = ok_all and ok
0238         if ok_all:
0239             self.capacity, self.by_key, self.used = staged.capacity, staged.by_key, staged.used
0240         return ok_all, details
0241 
0242     def reserve(self, resource: str, slot: str, key: str) -> tuple[bool, str]:
0243         if key in self.by_key:
0244             if self.by_key[key] != (resource, slot):
0245                 return False, "idempotency_key_reused_for_other_resource"
0246             return True, "duplicate_ignored"
0247         cap = self.capacity.get((resource, slot))
0248         if cap is None:
0249             return False, "capacity_unknown"
0250         holders = self.used.setdefault((resource, slot), [])
0251         if len(holders) >= cap:
0252             return False, "capacity_exhausted"
0253         holders.append(key)
0254         self.by_key[key] = (resource, slot)
0255         return True, "reserved"
```

## src/hospitalos/decision_support/planner.py L787–L821

```python
0787 def _reservation_requests(
0788     plan_actions: tuple[ActionSpec, ...], snapshot: PublicSnapshot
0789 ) -> list[tuple[str, str, str, int | None]]:
0790     start = snapshot.as_of
0791     transport, _ = team_capacity(snapshot.teams, "transport", start, 24)
0792     options = {o.option_id: o for o in snapshot.reinforcements}
0793     requests: list[tuple[str, str, str, int | None]] = []
0794     for a in plan_actions:
0795         if a.type == "reinforcement":
0796             requests.append((a.target, a.window_start.isoformat(), a.idempotency_key, 1))
0797             option = options.get(a.target)
0798             if option is not None and option.source == "shared_unit":
0799                 # F02/V4-R01: loans from one lender share its spare staff per hour, on the
0800                 # same common hourly grid as the cumulative check. V4-R02: an unidentified
0801                 # lender gives an unknown capacity, hence a refusal, never a skipped check.
0802                 lender = option.lending_unit or "UNKNOWN_LENDER"
0803                 spare = None
0804                 if option.lending_unit and option.lending_unit_scheduled is not None and (
0805                     option.lending_unit_minimum is not None
0806                 ):
0807                     spare = max(0, option.lending_unit_scheduled - option.lending_unit_minimum)
0808                 for h in touched_hours(option.start, option.end):
0809                     requests.append(
0810                         (
0811                             f"lend:{lender}:{option.skill}",
0812                             h.isoformat(),
0813                             f"{a.idempotency_key}:{h.isoformat()}",
0814                             spare,
0815                         )
0816                     )
0817         elif "transport_team" in a.resources:
0818             h = hour_index(start, a.window_start)
0819             cap = transport[h] if 0 <= h < len(transport) else 0
0820             requests.append(("transport", a.window_start.isoformat(), a.idempotency_key, cap))
0821     return requests
```
