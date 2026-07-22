# Laptop → Mini-PC Migration

Moves the complete working environment — code, datasets, live paper-trading
state, and the daily scheduled job — to the mini PC. Code travels via GitHub
(everything is pushed, including all worktree branches); only the gitignored
data travels by file copy.

## State of the laptop (already done)

- **Every branch is on origin** (verified; the one orphan branch was pushed).
- **The laptop's scheduled task `AgenticDesk-PaperTrade` is DISABLED** so two
  machines can never both run sessions and fork the paper state. Missed days
  during the migration are harmless by design — the next session settles
  whatever is queued against the newest completed bars.
- **Archive built:** `C:\Users\Jaydon.Yanez\Documents\minipc-migration\trading-data.tar.gz`
  containing, from the m12 worktree:
  | Contents | Size | Why copied |
  |---|---|---|
  | `data/validation/` | 547 MB | Dukascopy FX bars for M12 (Track A) — slow to re-download (per-IP throttling) |
  | `data/pit/` | 53 MB | PIT universe, 606-name stock bars, coverage report, EDGAR event ledger |
  | `data/stocks/` | 12 MB | survivor-universe bars (research history) |
  | `data/paper/` | <1 MB | **live paper-trading state — irreplaceable** (positions, queued orders, equity curve, idempotency keys, journal) |

  Not archived: `data/crypto/` (249 MB) — that research phase is closed and the
  data regenerates in ~10 min via `scripts/fetch_crypto.py` if ever needed.

## Steps on the mini PC

1. Copy `trading-data.tar.gz` over (USB / network share), e.g. to `D:\`.
2. Get the setup script (it lives in the repo — grab just the file first):
   download `scripts/setup_minipc.ps1` from the
   `feature/multi-regime-strategy-portfolio` branch on GitHub, or clone the
   repo and run it from there.
3. Run it:

       powershell -ExecutionPolicy Bypass -File setup_minipc.ps1 `
         -ArchivePath "D:\trading-data.tar.gz" -Root "C:\trading"

   It clones/updates the repo + m12 worktree, restores the data, installs
   dependencies, **runs the full test suite**, runs **one manual paper session**
   (proving quotes + news gate + pipeline end-to-end on that machine), and
   registers the weekday 18:30 scheduled task. It stops hard on any failure.
4. When it prints MIGRATION COMPLETE, delete the laptop task for good:

       schtasks /Delete /TN "AgenticDesk-PaperTrade" /F        (on the laptop)

5. Optional worktrees (docs/PR work) on the mini PC:

       git -C C:\trading\agentic-trading-desk worktree add ..\agentic-trading-desk-docs docs/project-engineering-documentation
       git -C C:\trading\agentic-trading-desk worktree add ..\agentic-trading-desk-m12-docs docs/roadmap-and-milestones-clean

## Rules

- **One machine runs paper sessions. Never two.** The state file is the single
  source of truth; parallel sessions would fork it silently.
- If the migration is delayed, the laptop task can be temporarily re-enabled
  (`schtasks /Change /TN "AgenticDesk-PaperTrade" /ENABLE`) — but then the
  archive must be rebuilt before migrating (the paper state will have moved on).

## After migration (Track A resumes there)

The mini PC then has everything Track A needs: the accepted 11.5 head, the M12
branch with all validation tooling + the 547 MB FX dataset, the clean docs
branch, and the M13–M19 implementation branches — plus the reviewer memo at
`docs/strategy-research/M12-DOD-DECISION-REQUEST.md`.
