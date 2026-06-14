from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Engine configuration, loaded from environment variables (or .env locally)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Capital.com
    capital_api_key: str = ""
    capital_identifier: str = ""
    capital_password: str = ""
    # "demo" (paper trading) or "live"
    capital_env: str = "demo"

    # Trading — "GOLD" est le code (epic) Capital.com pour l'or (XAU/USD)
    epic: str = "GOLD"
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
    def capital_base_url(self) -> str:
        if self.capital_env == "live":
            return "https://api-capital.backend-capital.com"
        return "https://demo-api-capital.backend-capital.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
