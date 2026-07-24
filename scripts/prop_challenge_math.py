"""Prop-challenge pass probabilities for OUR strategy, swept over risk levels.

Runs the barrier-race Monte Carlo (trading_desk.research.challenge) across
approximate 2026 rule sets and a grid of (annualized Sharpe, annualized vol)
configurations, then prints the honest economics: P(fund), expected fees per
funded account, and the capital-leverage translation back to the user's own
$1,000 (the only frame in which "8% per month" can be made to work).

Rule sets are APPROXIMATE and must be verified against the prop-firm research
document before any fee is paid. All simulations are end-of-day and
pessimistic on ties; firms with intraday checks are stricter.

Usage:
    PYTHONPATH="src" python scripts/prop_challenge_math.py
"""

from __future__ import annotations

import argparse

from trading_desk.research.challenge import (
    ChallengeRules,
    expected_fees_per_funded_account,
    simulate_challenge,
)

# Approximate 2026 rule sets (verify against docs/strategy-research research
# before paying): fee is USD for a ~$100k evaluation.
RULESETS: dict[str, tuple[float, tuple[ChallengeRules, ...]]] = {
    "ftmo-2step (10%->5%, 10% static, 5% daily, no time limit)": (
        600.0,
        (
            ChallengeRules(0.10, 0.10, False, 0.05, None, 4),
            ChallengeRules(0.05, 0.10, False, 0.05, None, 4),
        ),
    ),
    "generic-2step (8%->5%, 10% static, 5% daily)": (
        550.0,
        (
            ChallengeRules(0.08, 0.10, False, 0.05, None, 5),
            ChallengeRules(0.05, 0.10, False, 0.05, None, 5),
        ),
    ),
    "generic-1step (10%, 6% static, 3% daily)": (
        550.0,
        (ChallengeRules(0.10, 0.06, False, 0.03, None, 5),),
    ),
    "futures-style (6%, 3% TRAILING, 2% daily)": (
        165.0,
        (ChallengeRules(0.06, 0.03, True, 0.02, None, 7),),
    ),
}

SHARPES = (0.0, 0.12, 0.33, 0.80)
VOLS = (0.04, 0.08, 0.12, 0.16, 0.24, 0.32, 0.48)


def run_sweep(n_paths: int, max_days: int) -> None:
    for name, (fee, phases) in RULESETS.items():
        print(f"\n=== {name} | fee ${fee:.0f} ===")
        header = "ann_vol " + "".join(f"| S={s:<11.2f}" for s in SHARPES)
        print(header)
        print("-" * len(header))
        for vol in VOLS:
            cells = []
            for sharpe in SHARPES:
                out = simulate_challenge(phases, sharpe, vol, n_paths=n_paths, max_days=max_days)
                if out.p_total > 0:
                    cost = expected_fees_per_funded_account(out.p_total, fee)
                    cells.append(f"| {out.p_total:5.1%} ${cost:>6.0f}")
                else:
                    cells.append("| {:>13}".format("0% (never)"))
            print(f"{vol:7.0%} {''.join(cells)}")
        print(
            "(cell = P(funded) and expected total fees per funded account; "
            "timeout paths count as failures)"
        )


def capital_translation() -> None:
    print("\n=== Capital-leverage translation (why the challenge route exists) ===")
    own = 1_000.0
    print(f"8%/month of the user's own ${own:,.0f} = ${own * 0.08:,.0f}/month.")
    for funded, split in ((100_000.0, 0.80),):
        for monthly in (0.005, 0.01, 0.02):
            payout = funded * monthly * split
            print(
                f"${funded:,.0f} funded at {split:.0%} split, "
                f"{monthly:.1%}/month net -> ${payout:,.0f}/month "
                f"= {payout / own:.0%}/month of the user's own capital"
            )
    print(
        "A funded account needs only ~0.1%/month to match '8% of $1k'. "
        "The goal is reached through capital, not risk."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths", type=int, default=20_000)
    parser.add_argument("--max-days", type=int, default=400)
    args = parser.parse_args()
    run_sweep(args.paths, args.max_days)
    capital_translation()


if __name__ == "__main__":
    main()
