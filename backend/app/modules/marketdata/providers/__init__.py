from app.core.config import get_settings
from app.modules.marketdata.providers.base import MarketDataProvider


def get_provider() -> MarketDataProvider | None:
    """The configured provider, or None when market data is disabled."""
    s = get_settings()
    if s.marketdata_provider == "dukascopy":
        from app.modules.marketdata.providers.dukascopy import DukascopyProvider

        return DukascopyProvider(s.dukascopy_base_url, s.marketdata_timeout_seconds, s.marketdata_retries)
    return None
