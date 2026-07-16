"""Read-only structured news caution; no sentiment or direction authority."""

from datetime import datetime

from trading_desk.context.config import MarketContextConfiguration
from trading_desk.context.models import NewsContext, NewsItem, NewsState


def classify_news(
    items: tuple[NewsItem, ...],
    evaluation_timestamp: datetime,
    config: MarketContextConfiguration,
) -> NewsContext:
    visible = tuple(item for item in items if item.published_at <= evaluation_timestamp)
    if not visible:
        return NewsContext(state=NewsState.CLEAR)
    latest = max(visible, key=lambda item: item.published_at)
    age_minutes = int((evaluation_timestamp - latest.published_at).total_seconds() // 60)
    if latest.scheduled:
        return NewsContext(
            state=NewsState.SCHEDULED,
            latest_news_item_id=latest.news_item_id,
            age_seconds=max(0, age_minutes * 60),
        )
    if age_minutes <= config.unscheduled_news_caution_minutes:
        state = NewsState.UNSCHEDULED_CAUTION
    else:
        state = NewsState.STALE
    return NewsContext(
        state=state,
        latest_news_item_id=latest.news_item_id,
        age_seconds=max(0, age_minutes * 60),
    )
