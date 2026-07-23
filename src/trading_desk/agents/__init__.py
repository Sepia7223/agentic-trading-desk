"""Advisory AI agents — SHADOW MODE ONLY (blueprint Phase 3).

LLM proposes, rules dispose: agents transform curated input packets into typed
pydantic artifacts recorded in an append-only store. In shadow mode nothing is
consumed by the trading pipeline — artifacts accumulate alongside paper
trading so their calibration can be scored on FORWARD data (the only
evaluation the LLM look-ahead literature permits). The only coupling ever
permitted later is attenuation: a packet may shrink or veto a trade, never
enlarge one, and an absent/invalid packet has zero effect.

No agent holds execution authority. Live API calls require ANTHROPIC_API_KEY;
absent a key, agents are inert and tests run against the mock client.
"""

from trading_desk.agents.client import LLMClient, MockLLMClient
from trading_desk.agents.models import (
    AdvisoryPacket,
    Evidence,
    NewsSignal,
    RegimeAssessment,
)
from trading_desk.agents.news_agent import classify_news
from trading_desk.agents.store import ArtifactStore
from trading_desk.agents.synthesizer import synthesize_advisory
from trading_desk.agents.validators import validate_evidence

__all__ = [
    "AdvisoryPacket",
    "ArtifactStore",
    "Evidence",
    "LLMClient",
    "MockLLMClient",
    "NewsSignal",
    "RegimeAssessment",
    "classify_news",
    "synthesize_advisory",
    "validate_evidence",
]
