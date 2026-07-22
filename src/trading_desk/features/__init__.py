"""Point-in-time feature store — the structural leakage defense.

Every stored fact carries two timestamps: ``event_time`` (when it happened) and
``knowledge_time`` (when we could have known it — e.g. EDGAR acceptance, news
feed arrival). Queries answer exactly one question — "features for universe U
as-of decision time T" — and can never return a row whose knowledge_time
postdates T. Signals may read data ONLY through this API.
"""

from trading_desk.features.store import FeatureStore

__all__ = ["FeatureStore"]
