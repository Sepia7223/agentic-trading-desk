"""Research-side math that never touches the trading path.

Everything in this package is analysis tooling (e.g. prop-challenge
first-passage simulation). Nothing here may be imported by pretrade, paper,
risk, or execution modules — research informs human decisions, not trades.
"""
