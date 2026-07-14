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

    # Paper trading loop (data -> signal -> risk -> order)
    trading_loop_enabled: bool = True
    trade_interval_seconds: int = 300
    strategy_name: str = "lightgbm"
    model_granularity: str = "M5"
    decision_candles: int = 150
    stop_loss_pct: float = 0.005
    risk_reward_ratio: float = 1.5
    # Certains comptes/instruments Capital.com exigent un guaranteed stop. Quand
    # activé, le trader force guaranteedStop=true et élargit le stop pour
    # respecter la distance minimale du broker (minGuaranteedStopDistance).
    use_guaranteed_stop: bool = True
    # Marge de sécurité ajoutée au-dessus de la distance minimale exigée par le
    # broker (0.1 = +10 %), pour éviter les rejets aux frontières.
    stop_distance_buffer: float = 0.1

    # Learning loop (periodic retraining + champion/challenger). Off by default:
    # retraining is heavy, opt in explicitly.
    learning_enabled: bool = False
    learning_interval_seconds: int = 86400

    # Data ingestion
    ingest_enabled: bool = True
    ingest_granularities: str = "M1,M5,M15"
    ingest_interval_seconds: int = 60
    ingest_recent_count: int = 50

    # Dukascopy historical backfill — symbole et facteur de prix (XAUUSD = 3
    # décimales, donc diviseur 1000).
    dukascopy_symbol: str = "XAUUSD"
    dukascopy_price_divisor: float = 1000.0

    # Données macro : instrument corrélé (EUR/USD = proxy inverse du dollar).
    # macro_instrument = clé en base ; capital_macro_epic = epic Capital.com live.
    macro_instrument: str = "EURUSD"
    capital_macro_epic: str = "EURUSD"

    # Taux réels US (FRED DFII10) — driver fondamental de l'or. Série journalière
    # stockée sous granularité "D" et clé instrument = rates_instrument.
    rates_series: str = "DFII10"
    rates_instrument: str = "DFII10"

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
