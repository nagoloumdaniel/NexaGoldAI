from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Engine configuration, loaded from environment variables (or .env locally)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # OANDA
    oanda_api_key: str = ""
    oanda_account_id: str = ""
    # "practice" (demo) or "live"
    oanda_env: str = "practice"

    # Trading
    instrument: str = "XAU_USD"
    # Hard kill switch: when False the engine never sends orders, whatever the signal.
    trading_enabled: bool = False

    # Risk limits (enforced by RiskManager before any order is sent)
    max_risk_per_trade_pct: float = 1.0
    max_daily_loss_pct: float = 3.0
    max_open_positions: int = 1

    # Infra
    database_url: str = ""
    redis_url: str = ""

    @property
    def oanda_base_url(self) -> str:
        if self.oanda_env == "live":
            return "https://api-fxtrade.oanda.com"
        return "https://api-fxpractice.oanda.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
