from tests.opportunity_helpers import candidate

from trading_desk.opportunity.correlation import suppress_candidates
from trading_desk.opportunity.models import CandidateStatus, OpportunityRejectionCode


def test_duplicates_and_existing_positions_are_suppressed() -> None:
    item = candidate()
    duplicate = suppress_candidates((item, item))
    assert duplicate[0].status is CandidateStatus.ELIGIBLE
    assert OpportunityRejectionCode.DUPLICATE_CANDIDATE in duplicate[1].rejection_reasons
    existing = suppress_candidates((item,), existing_epics=(item.epic,))
    assert OpportunityRejectionCode.EXISTING_POSITION_CONFLICT in existing[0].rejection_reasons
