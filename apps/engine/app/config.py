from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Engine configuration, loaded from environment variables (or .env locally)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # MetaTrader 5 — terminal installé localement (Windows). Le moteur se
    # connecte au terminal via le paquet Python MetaTrader5 (IPC), qui lance le
    # terminal automatiquement s'il n'est pas déjà ouvert.
    #   mt5_login    : numéro du compte (démo pour commencer)
    #   mt5_password : mot de passe du compte
    #   mt5_server   : serveur du broker (ex. "MetaQuotes-Demo")
    # Laisser mt5_login vide pour se rattacher au compte déjà connecté dans le
    # terminal ouvert.
    mt5_login: str = ""
    mt5_password: str = ""
    mt5_server: str = ""
    # Mode rattachement : ignore login/password et utilise le compte déjà
    # connecté dans le terminal (session enregistrée par MT5). Pratique quand
    # le mot de passe MT5 n'est pas connu ; le verrou démo du Trader vérifie
    # de toute façon le type de compte auprès du terminal.
    mt5_attach: bool = False
    mt5_terminal_path: str = r"C:\Program Files\MetaTrader 5\terminal64.exe"
    # Décalage heure serveur broker -> UTC (la plupart des brokers MT5 sont en
    # UTC+2 l'hiver / UTC+3 l'été). Sert à stocker les bougies en UTC, alignées
    # avec l'historique Dukascopy.
    mt5_utc_offset_hours: float = 0.0
    # "demo" (paper trading) ou "live" — doit refléter le TYPE du compte MT5 ;
    # le Trader vérifie aussi account_info() côté broker avant tout ordre.
    broker_env: str = "demo"

    # Trading — symbole MT5 de l'or (XAU/USD). Selon le broker : XAUUSD,
    # XAUUSD.a, GOLD... Vérifier dans le Market Watch du terminal.
    symbol: str = "XAUUSD"
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
    paper_validation_min_trades: int = 100
    # Marge de sécurité ajoutée au-dessus de la distance de stop minimale du
    # broker (0.1 = +10 %), pour éviter les rejets aux frontières.
    stop_distance_buffer: float = 0.1
    # Garde d'exécution : aucun ordre si le spread relatif dépasse ce plafond
    # (protège des spreads élargis au rollover / annonces / faible liquidité).
    max_spread_pct: float = 0.001
    # Mode scalp (stratégie scalp_m5) : clôture anticipée au premier profit.
    #   profit_check_interval_seconds : cadence du moniteur qui surveille le
    #     P&L des positions ouvertes (bien plus rapide que la boucle de signal).
    #   profit_close_min_net : gain net minimal (devise du compte) exigé avant
    #     de clôturer — coussin contre latence de clôture + slippage. Valeur de
    #     départ ; le tuner adaptatif l'ajuste ensuite dans ses bornes.
    #   scalp_adapt_enabled : active l'auto-apprentissage borné des paramètres.
    profit_check_interval_seconds: int = 5
    profit_close_min_net: float = 0.5
    scalp_adapt_enabled: bool = True
    # Applique réellement le filtre de régime (exclude BUY en BULLISH_TREND)
    # au lieu de le journaliser en shadow uniquement. À n'activer qu'après
    # validation historique du filtre.
    regime_filter_enforced: bool = False
    # Autorise le côté SELL de la stratégie expected-return (rejeté par la
    # validation historique — garder False sauf nouvelle validation).
    expected_return_allow_short: bool = False

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
    # macro_instrument = clé en base ; mt5_macro_symbol = symbole MT5 live.
    macro_instrument: str = "EURUSD"
    mt5_macro_symbol: str = "EURUSD"

    # Taux réels US (FRED DFII10) — driver fondamental de l'or. Série journalière
    # stockée sous granularité "D" et clé instrument = rates_instrument.
    rates_series: str = "DFII10"
    rates_instrument: str = "DFII10"

    # Infra
    database_url: str = ""
    redis_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
