from tests.opportunity_helpers import NOW, candidate

from trading_desk.opportunity.config import OpportunityEngineConfiguration
from trading_desk.opportunity.ranking import rank_candidates


def test_ranking_is_stable_and_bounded() -> None:
    item = candidate()
    config = OpportunityEngineConfiguration(enabled=True, maximum_candidates_sent_to_risk=1)
    first = rank_candidates("cycle", NOW, (item,), config)
    second = rank_candidates("cycle", NOW, (item,), config)
    assert first == second
    assert first.selected_candidate_ids == (item.candidate_id,)
