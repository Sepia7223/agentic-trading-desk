# Independent Reviews

This directory stores milestone review records separately from implementation specifications.

Each review should contain:

- repository and PR identifier;
- reviewed base SHA and head SHA;
- specification revision reviewed;
- CI and local validation evidence;
- findings ordered by severity;
- authority-boundary assessment;
- operational evidence assessment;
- required corrective actions;
- final verdict;
- reviewer and review timestamp.

## Verdicts

- `ACCEPTED`: all blocking requirements are satisfied.
- `PARTIALLY_CERTIFIED`: implementation is accepted but specific real-world evidence remains unavailable for legitimate operational reasons.
- `REJECTED`: blocking requirements remain unsatisfied.
- `SUPERSEDED`: a later review replaces the decision.

Reviews must distinguish software correctness from trading-strategy validity and operational certification. Passing unit tests cannot substitute for historical validation, and historical validation cannot substitute for real Demo lifecycle evidence.
