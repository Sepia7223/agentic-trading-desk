"""Tests for the shadow advisory agents (mocked LLM; fully offline)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from trading_desk.agents import (
    ArtifactStore,
    Evidence,
    MockLLMClient,
    NewsSignal,
    classify_news,
    synthesize_advisory,
    validate_evidence,
)
from trading_desk.agents.models import AdvisoryPacket, ArtifactEnvelope
from trading_desk.agents.validators import EvidenceError

AS_OF = datetime(2026, 7, 22, 21, 0, tzinfo=UTC)
SOURCES = {
    "n1": "Acme Corp announced record quarterly earnings, beating estimates.",
    "n2": "Analysts remain divided on Acme's guidance for next year.",
}

GOOD_A1 = json.dumps(
    {
        "event_type": "earnings",
        "direction": "bullish",
        "relevance": "direct",
        "horizon": "days",
        "confidence": 0.7,
        "rationale": "Earnings beat with direct instrument relevance.",
        "evidence": [{"source_id": "n1", "quote": "record quarterly earnings"}],
        "abstained": False,
    }
)


# --------------------------------------------------------------------- A1


def test_a1_valid_output_becomes_signal():
    client = MockLLMClient([GOOD_A1])
    signal = classify_news(client, instrument="ACME", sources=SOURCES, as_of=AS_OF)
    assert signal is not None
    assert signal.direction == "bullish"
    assert signal.shadow is True
    assert signal.agent == "a1-news"


def test_a1_fabricated_quote_is_discarded():
    fabricated = json.loads(GOOD_A1)
    fabricated["evidence"] = [{"source_id": "n1", "quote": "guaranteed 300% rally incoming"}]
    client = MockLLMClient([json.dumps(fabricated)])
    assert classify_news(client, instrument="ACME", sources=SOURCES, as_of=AS_OF) is None


def test_a1_malformed_json_discarded_not_repaired():
    client = MockLLMClient(["I think the stock looks bullish overall!"])
    assert classify_news(client, instrument="ACME", sources=SOURCES, as_of=AS_OF) is None


def test_a1_out_of_vocabulary_discarded():
    bad = json.loads(GOOD_A1)
    bad["direction"] = "to_the_moon"
    client = MockLLMClient([json.dumps(bad)])
    assert classify_news(client, instrument="ACME", sources=SOURCES, as_of=AS_OF) is None


def test_a1_run_id_deterministic():
    s1 = classify_news(MockLLMClient([GOOD_A1]), instrument="ACME", sources=SOURCES, as_of=AS_OF)
    s2 = classify_news(MockLLMClient([GOOD_A1]), instrument="ACME", sources=SOURCES, as_of=AS_OF)
    assert s1 is not None and s2 is not None
    assert s1.run_id == s2.run_id  # same packet, same day -> same identity


# --------------------------------------------------------------------- A4


def make_signal() -> NewsSignal:
    payload = json.loads(GOOD_A1)
    input_sha = "a" * 64
    return NewsSignal(
        run_id=ArtifactEnvelope.make_run_id("a1-news", AS_OF, input_sha),
        agent="a1-news",
        model_id="mock",
        prompt_version="a1-news-v1",
        as_of=AS_OF,
        input_sha256=input_sha,
        instrument="ACME",
        **payload,
    )


def test_a4_bear_pass_can_only_reduce_scalar():
    draft = json.dumps(
        {
            "stance": "supportive",
            "size_scalar": 1.0,
            "veto": False,
            "key_risks": ["earnings gap"],
            "critique_summary": "",
        }
    )
    critique = json.dumps(
        {
            "revised_stance": "cautionary",
            "revised_size_scalar": 0.5,
            "revised_veto": False,
            "critique_summary": "overconfident on one print",
        }
    )
    packet = synthesize_advisory(
        MockLLMClient([draft, critique]),
        instrument="ACME",
        news_signals=[make_signal()],
        quant_features={"momentum_rank": 0.8},
        as_of=AS_OF,
    )
    assert packet.size_scalar == 0.5
    assert packet.stance == "cautionary"


def test_a4_critique_cannot_raise_scalar():
    draft = json.dumps(
        {
            "stance": "cautionary",
            "size_scalar": 0.5,
            "veto": False,
            "key_risks": [],
            "critique_summary": "",
        }
    )
    critique = json.dumps(
        {
            "revised_stance": "supportive",
            "revised_size_scalar": 1.0,
            "revised_veto": False,
            "critique_summary": "actually it's fine",
        }
    )
    packet = synthesize_advisory(
        MockLLMClient([draft, critique]),
        instrument="ACME",
        news_signals=[],
        quant_features={},
        as_of=AS_OF,
    )
    assert packet.size_scalar == 0.5  # min(draft, revision): never raised


def test_a4_invalid_output_degrades_to_no_effect():
    packet = synthesize_advisory(
        MockLLMClient(["not json at all"]),
        instrument="ACME",
        news_signals=[],
        quant_features={},
        as_of=AS_OF,
    )
    assert packet.stance == "no_data"
    assert packet.size_scalar == 1.0
    assert packet.veto is False


def test_a4_veto_sticks_from_either_pass():
    draft = json.dumps(
        {
            "stance": "cautionary",
            "size_scalar": 0.8,
            "veto": True,
            "key_risks": [],
            "critique_summary": "",
        }
    )
    critique = json.dumps(
        {
            "revised_stance": "cautionary",
            "revised_size_scalar": 0.8,
            "revised_veto": False,
            "critique_summary": "keep",
        }
    )
    packet = synthesize_advisory(
        MockLLMClient([draft, critique]),
        instrument="ACME",
        news_signals=[],
        quant_features={},
        as_of=AS_OF,
    )
    assert packet.veto is True  # a veto is never un-vetoed downstream


def test_scalar_bounds_enforced_by_type():
    with pytest.raises(ValidationError):
        AdvisoryPacket(
            run_id="x" * 20,
            agent="a4-synth",
            model_id="mock",
            prompt_version="v",
            as_of=AS_OF,
            input_sha256="a" * 64,
            instrument="ACME",
            stance="supportive",
            size_scalar=1.5,  # amplification is structurally impossible
            veto=False,
            key_risks=(),
            critique_summary="",
        )


# ----------------------------------------------------------------- validators


def test_evidence_validator_verbatim_and_unknown_source():
    validate_evidence([Evidence(source_id="n1", quote="record quarterly earnings")], SOURCES)
    with pytest.raises(EvidenceError, match="verbatim"):
        validate_evidence(
            [Evidence(source_id="n1", quote="Record Quarterly Earnings!")],
            SOURCES,
        )
    with pytest.raises(EvidenceError, match="unknown source"):
        validate_evidence([Evidence(source_id="zzz", quote="x")], SOURCES)


# ---------------------------------------------------------------------- store


def test_store_appends_and_scores_brier(tmp_path: Path):
    store = ArtifactStore(tmp_path)
    signal = make_signal()
    store.append(signal)
    assert len(store.load_raw("a1-news")) == 1
    score, n = store.brier_score("a1-news")
    assert score is None and n == 0  # no outcomes yet
    store.record_outcome(signal.run_id, "a1-news", 0.7, outcome=True)
    store.record_outcome(signal.run_id, "a1-news", 0.7, outcome=False)
    score, n = store.brier_score("a1-news")
    assert n == 2
    assert score == pytest.approx((0.3**2 + 0.7**2) / 2)
