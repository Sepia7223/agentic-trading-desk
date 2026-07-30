"""Build insider-purchase features from the SEC Form 345 quarterly datasets.

Extracts OPEN-MARKET PURCHASES (TRANS_CODE == 'P', acquired) by OFFICERS and
DIRECTORS for the point-in-time universe, and writes:

  1. ``data/pit/insider_purchases.parquet`` — one row per purchase with
     event_time (transaction date) and knowledge_time (FILING_DATE + 1 day —
     conservative: most Form 4s are accepted after hours, so the information
     is tradeable at the next session, per the blueprint's causality rule);
  2. FeatureStore appends under source ``insider`` (root data/pit/features).

Sales are ignored by design: the literature (Lakonishok-Lee, Cohen-Malloy-
Pomorski) finds insider sales carry almost no information. Cluster detection
(>=2 distinct insider buyers within a trailing window) happens at signal-
evaluation time so the window stays a registered, tunable trial parameter.

Usage:
    PYTHONPATH=src python scripts/build_insider_features.py
"""

from __future__ import annotations

import argparse
import io
import json
import zipfile
from pathlib import Path

import pandas as pd

from trading_desk.features import FeatureStore


def load_universe_tickers(pit_dir: Path) -> set[str]:
    uni = json.loads(
        (pit_dir / "universe_2021-01-01_2026-06-30.json").read_text(encoding="utf-8")
    )
    return {t.upper() for t in uni["intervals"]}


def _read_tsv(zf: zipfile.ZipFile, name: str, usecols: list[str]) -> pd.DataFrame:
    with zf.open(name) as fh:
        return pd.read_csv(
            io.TextIOWrapper(fh, encoding="utf-8", errors="replace"),
            sep="\t",
            usecols=lambda c: c in set(usecols),
            dtype=str,
            on_bad_lines="skip",
        )


def extract_quarter(path: Path, universe: set[str]) -> pd.DataFrame:
    """Officer/director open-market purchases for universe tickers, one zip."""

    zf = zipfile.ZipFile(path)
    sub = _read_tsv(
        zf,
        "SUBMISSION.tsv",
        ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERTRADINGSYMBOL"],
    )
    sub = sub[sub["DOCUMENT_TYPE"].isin(["4", "4/A"])]
    sub["symbol"] = sub["ISSUERTRADINGSYMBOL"].fillna("").str.upper().str.strip()
    sub = sub[sub["symbol"].isin(universe)]
    if sub.empty:
        return pd.DataFrame()

    owners = _read_tsv(
        zf,
        "REPORTINGOWNER.tsv",
        ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP"],
    )
    rel = owners["RPTOWNER_RELATIONSHIP"].fillna("").str.upper()
    owners = owners[rel.str.contains("OFFICER") | rel.str.contains("DIRECTOR")]

    trans = _read_tsv(
        zf,
        "NONDERIV_TRANS.tsv",
        [
            "ACCESSION_NUMBER",
            "TRANS_DATE",
            "TRANS_CODE",
            "TRANS_SHARES",
            "TRANS_PRICEPERSHARE",
            "TRANS_ACQUIRED_DISP_CD",
        ],
    )
    trans = trans[
        (trans["TRANS_CODE"] == "P") & (trans["TRANS_ACQUIRED_DISP_CD"] == "A")
    ]
    if trans.empty:
        return pd.DataFrame()

    merged = trans.merge(sub, on="ACCESSION_NUMBER", how="inner").merge(
        owners, on="ACCESSION_NUMBER", how="inner"
    )
    if merged.empty:
        return pd.DataFrame()
    shares = pd.to_numeric(merged["TRANS_SHARES"], errors="coerce")
    price = pd.to_numeric(merged["TRANS_PRICEPERSHARE"], errors="coerce")
    out = pd.DataFrame(
        {
            "ticker": merged["symbol"],
            "event_time": pd.to_datetime(
                merged["TRANS_DATE"], errors="coerce", utc=True, format="mixed"
            ),
            "filing_date": pd.to_datetime(
                merged["FILING_DATE"], errors="coerce", utc=True, format="mixed"
            ),
            "owner_cik": merged["RPTOWNERCIK"].astype(str),
            "dollars": (shares * price).fillna(0.0),
            "shares": shares.fillna(0.0),
        }
    )
    out = out.dropna(subset=["event_time", "filing_date"])
    # knowledge_time: filing date + 1 day (conservative post-close causality)
    out["knowledge_time"] = out["filing_date"] + pd.Timedelta(days=1)
    # data-quality guard: transactions "filed" before they happened are junk
    out = out[out["knowledge_time"] >= out["event_time"]]
    return out.drop(columns=["filing_date"])


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--form345-dir", default="data/pit/form345")
    p.add_argument("--pit-dir", default="data/pit")
    p.add_argument("--out", default="data/pit/insider_purchases.parquet")
    args = p.parse_args(argv)
    pit = Path(args.pit_dir)
    universe = load_universe_tickers(pit)
    frames: list[pd.DataFrame] = []
    for path in sorted(Path(args.form345_dir).glob("*_form345.zip")):
        piece = extract_quarter(path, universe)
        rows = 0 if piece.empty else len(piece)
        print(f"{path.name}: {rows} officer/director purchases in universe")
        if rows:
            frames.append(piece)
    if not frames:
        print("NO DATA - nothing written")
        return 1
    purchases = pd.concat(frames, ignore_index=True).sort_values("knowledge_time")
    purchases.to_parquet(args.out, index=False)
    print(f"wrote {args.out}: {len(purchases)} purchases, "
          f"{purchases['ticker'].nunique()} tickers, "
          f"{purchases['event_time'].min().date()}..{purchases['event_time'].max().date()}")

    # feature-store append: raw purchase events (cluster logic lives downstream)
    store = FeatureStore(pit / "features")
    store.append(
        "insider",
        purchases[
            ["ticker", "event_time", "knowledge_time", "dollars", "owner_cik"]
        ].rename(columns={"dollars": "purchase_dollars"}),
    )
    print("feature store updated:", store.describe().get("insider"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
