# Operations Documentation

Operational documents describe how to run, observe, certify, recover, and migrate the trading desk without changing trading authority.

Expected contents include:

- IG Demo certification procedures;
- environment and secret-management runbooks;
- scheduler and campaign operations;
- backup and restore procedures;
- incident records and corrective actions;
- laptop-to-Mini-PC migration procedure;
- release and rollback checklists.

Operational evidence must be sanitized. Never commit credentials, OAuth tokens, API keys, complete account identifiers, raw broker responses containing sensitive fields, local `.env` files, or workstation-specific secret paths.

No runbook may authorize forced trades, gate reduction, automatic retries after ambiguous broker outcomes, account switching, or Live execution.
