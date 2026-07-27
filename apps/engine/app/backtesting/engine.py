"""Backtest évènementiel pour stratégies à règles multi-timeframes.

Rejoue bougie M1 par bougie M1 : à chaque clôture M1, les fenêtres M5/M15/H1
sont reconstruites à partir du M1 (bougies CLOSES uniquement — aucune bougie
future, aucune bougie en cours), la stratégie est évaluée exactement comme en
live, et les ordres sont simulés avec des coûts explicites :

- exécution à l'OUVERTURE de la bougie M1 suivante (latence d'une bougie) ;
- demi-spread payé à l'entrée ET à la sortie, slippage ajouté sur les fills
  au marché et les stops (les stops glissent contre nous, jamais en notre
  faveur) ;
- bracket SL/TP intrabar : si le stop et l'objectif sont touchés dans la même
  bougie M1, hypothèse PESSIMISTE : le stop passe en premier ;
- une seule position à la fois (parité avec MAX_OPEN_POSITIONS=1).

Le moteur est volontairement hostile : son travail est d'invalider la
stratégie, pas de la flatter.
"""

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from app.strategy.base import Action, Strategy

logger = logging.getLogger("nexagold.backtest")

_TF_MINUTES = {"M5": 5, "M15": 15, "H1": 60}


@dataclass
class CostModel:
    # Spread relatif total (bid-ask / mid). XAUUSD démo : ~0.35 USD sur ~3300.
    spread_pct: float = 0.00012
    # Slippage relatif par exécution au marché / stop.
    slippage_pct: float = 0.00003
    # Commission par side (0 sur la plupart des comptes spread-only).
    commission_pct: float = 0.0


@dataclass
class BacktestTrade:
    direction: str
    signal_time: str
    entry_time: str
    entry_price: float
    stop_price: float
    target_price: float
    exit_time: str | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    result_r: float | None = None
    mfe_r: float = 0.0
    mae_r: float = 0.0
    holding_bars: int = 0
    costs_pct: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def resample_m1(m1: list[dict], minutes: int) -> list[dict]:
    """Agrège des bougies M1 closes en bougies `minutes` (label = début de
    période, convention MT5). Seules les périodes ENTIÈREMENT couvertes par la
    dernière M1 disponible sont retournées closes — l'appelant tronque."""
    out: list[dict] = []
    current: dict | None = None
    current_key: datetime | None = None
    for bar in m1:
        t = datetime.fromisoformat(bar["time"])
        key = t.replace(
            minute=(t.minute // minutes) * minutes if minutes < 60 else 0,
            second=0,
            microsecond=0,
        )
        if minutes == 60:
            key = key.replace(minute=0)
        if current_key != key:
            if current is not None:
                out.append(current)
            current_key = key
            current = {
                "time": key.strftime("%Y-%m-%dT%H:%M:%S"),
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume": bar.get("volume", 0),
            }
        else:
            current["high"] = max(current["high"], bar["high"])
            current["low"] = min(current["low"], bar["low"])
            current["close"] = bar["close"]
            current["volume"] += bar.get("volume", 0)
    if current is not None:
        out.append(current)
    return out


class EventBacktester:
    """Rejoue une stratégie (contrat Strategy + extra_granularities) sur M1."""

    def __init__(
        self,
        strategy: Strategy,
        costs: CostModel | None = None,
        window_bars: int = 240,
        risk_pct_per_trade: float = 0.5,
        max_holding_bars: int = 1440,  # 24 h : filet de sécurité
    ):
        self._strategy = strategy
        self._costs = costs or CostModel()
        self._window = window_bars
        self._risk_pct = risk_pct_per_trade
        self._max_holding = max_holding_bars

    # -- Simulation d'exécution ----------------------------------------------

    def _fill_entry(self, direction: str, next_open: float) -> tuple[float, float]:
        c = self._costs
        adj = next_open * (c.spread_pct / 2 + c.slippage_pct + c.commission_pct)
        entry = next_open + adj if direction == "BUY" else next_open - adj
        costs_pct = c.spread_pct / 2 + c.slippage_pct + c.commission_pct
        return entry, costs_pct

    def _exit_price(self, direction: str, raw: float, is_stop: bool) -> float:
        c = self._costs
        adj_pct = c.spread_pct / 2 + c.commission_pct + (c.slippage_pct if is_stop else 0.0)
        adj = raw * adj_pct
        return raw - adj if direction == "BUY" else raw + adj

    def _manage_position(
        self, trade: BacktestTrade, bar: dict, bar_index_in_trade: int
    ) -> bool:
        """Avance la position d'une bougie M1. True si la position est close."""
        direction = trade.direction
        risk = abs(trade.entry_price - trade.stop_price)
        if risk <= 0:
            trade.exit_reason = "INVALID_RISK"
            trade.result_r = 0.0
            return True

        high, low, close = bar["high"], bar["low"], bar["close"]
        if direction == "BUY":
            trade.mfe_r = max(trade.mfe_r, (high - trade.entry_price) / risk)
            trade.mae_r = min(trade.mae_r, (low - trade.entry_price) / risk)
            stop_hit = low <= trade.stop_price
            target_hit = high >= trade.target_price
        else:
            trade.mfe_r = max(trade.mfe_r, (trade.entry_price - low) / risk)
            trade.mae_r = min(trade.mae_r, (trade.entry_price - high) / risk)
            stop_hit = high >= trade.stop_price
            target_hit = low <= trade.target_price

        trade.holding_bars = bar_index_in_trade
        exit_raw = None
        if stop_hit:  # pessimiste : stop d'abord, même si le TP est aussi touché
            exit_raw, trade.exit_reason, is_stop = trade.stop_price, "STOP_LOSS", True
        elif target_hit:
            exit_raw, trade.exit_reason, is_stop = trade.target_price, "TAKE_PROFIT", False
        elif bar_index_in_trade >= self._max_holding:
            exit_raw, trade.exit_reason, is_stop = close, "TIMEOUT", False

        if exit_raw is None:
            return False
        fill = self._exit_price(direction, exit_raw, is_stop)
        trade.exit_time = bar["time"]
        trade.exit_price = round(fill, 3)
        signed = fill - trade.entry_price if direction == "BUY" else trade.entry_price - fill
        trade.result_r = round(signed / risk, 4)
        trade.costs_pct = round(
            trade.costs_pct + self._costs.spread_pct / 2 + 2 * self._costs.commission_pct,
            8,
        )
        return True

    # -- Boucle principale ----------------------------------------------------

    def run(self, m1: list[dict]) -> dict:
        strategy = self._strategy
        window = self._window
        tf_series = {
            gran: resample_m1(m1, _TF_MINUTES[gran])
            for gran in strategy.extra_granularities
            if gran in _TF_MINUTES
        }
        # Index de la prochaine bougie TF *ouverte* pour chaque temps M1 :
        # une bougie TF d'ouverture T est close quand T + step <= t.
        tf_open_times = {
            gran: [datetime.fromisoformat(c["time"]) for c in series]
            for gran, series in tf_series.items()
        }

        trades: list[BacktestTrade] = []
        hold_reasons: dict[str, int] = {}
        open_trade: BacktestTrade | None = None
        entry_bar_index: int | None = None
        pending: tuple[str, dict, str] | None = None  # (direction, features, signal_time)
        equity = 1.0
        equity_curve: list[tuple[str, float]] = []
        evaluations = 0
        signals = 0

        start = max(window, 61)
        for i in range(start, len(m1)):
            bar = m1[i]
            bar_time = datetime.fromisoformat(bar["time"])

            # 1) Gestion de la position ouverte (sur la bougie courante).
            if open_trade is not None:
                closed = self._manage_position(open_trade, bar, i - entry_bar_index)
                if closed:
                    equity *= 1.0 + (self._risk_pct / 100.0) * (open_trade.result_r or 0.0)
                    equity_curve.append((bar["time"], round(equity, 6)))
                    trades.append(open_trade)
                    open_trade = None
                    entry_bar_index = None
                continue  # une seule position : pas de nouveau signal pendant

            # 2) Fill d'un signal émis à la clôture précédente.
            if pending is not None:
                direction, features, signal_time = pending
                pending = None
                entry, entry_costs = self._fill_entry(direction, bar["open"])
                stop_pct = float(features.get("stop_loss_pct") or 0.0)
                rr = float(features.get("risk_reward_ratio") or 2.0)
                if stop_pct > 0:
                    if direction == "BUY":
                        stop = entry * (1 - stop_pct)
                        target = entry * (1 + stop_pct * rr)
                    else:
                        stop = entry * (1 + stop_pct)
                        target = entry * (1 - stop_pct * rr)
                    open_trade = BacktestTrade(
                        direction=direction,
                        signal_time=signal_time,
                        entry_time=bar["time"],
                        entry_price=round(entry, 3),
                        stop_price=round(stop, 3),
                        target_price=round(target, 3),
                        costs_pct=entry_costs,
                        reason=str(features.get("setup_id") or ""),
                    )
                    entry_bar_index = i
                    mark = getattr(strategy, "mark_signal_consumed", None)
                    if callable(mark):
                        mark(features.get("trigger_bar_time") or features.get("m5_bar_time"))
                    # La bougie de fill peut déjà toucher le bracket.
                    closed = self._manage_position(open_trade, bar, 0)
                    if closed:
                        equity *= 1.0 + (self._risk_pct / 100.0) * (
                            open_trade.result_r or 0.0
                        )
                        equity_curve.append((bar["time"], round(equity, 6)))
                        trades.append(open_trade)
                        open_trade = None
                        entry_bar_index = None
                    continue

            # 3) Évaluation de la stratégie à la CLÔTURE de la bougie i.
            m1_window = m1[max(0, i + 1 - window) : i + 1]
            extra: dict[str, list[dict]] = {}
            for gran, series in tf_series.items():
                step = timedelta(minutes=_TF_MINUTES[gran])
                # Nombre de bougies TF closes à la clôture de la bougie M1 i.
                closed_count = 0
                opens = tf_open_times[gran]
                lo, hi = 0, len(opens)
                cutoff = bar_time + timedelta(minutes=1)
                while lo < hi:
                    mid = (lo + hi) // 2
                    if opens[mid] + step <= cutoff:
                        lo = mid + 1
                    else:
                        hi = mid
                closed_count = lo
                closed = series[max(0, closed_count - window) : closed_count]
                if closed:
                    # evaluate() écarte la dernière bougie (supposée en cours) :
                    # on ajoute une sentinelle pour ne pas perdre une vraie close.
                    closed = closed + [dict(closed[-1])]
                extra[gran] = closed

            evaluations += 1
            signal = strategy.evaluate(m1_window + [dict(m1_window[-1])], extra=extra)
            if signal.action == Action.HOLD:
                key = signal.reason.split("(")[0].strip()[:60]
                hold_reasons[key] = hold_reasons.get(key, 0) + 1
                continue
            signals += 1
            pending = (
                "BUY" if signal.action == Action.BUY else "SELL",
                signal.features,
                bar["time"],
            )

        report = self._report(trades, hold_reasons, equity_curve, evaluations, signals)
        report["open_position_at_end"] = open_trade.to_dict() if open_trade else None
        return report

    # -- Métriques ------------------------------------------------------------

    def _report(
        self,
        trades: list[BacktestTrade],
        hold_reasons: dict[str, int],
        equity_curve: list[tuple[str, float]],
        evaluations: int,
        signals: int,
    ) -> dict:
        rs = [t.result_r for t in trades if t.result_r is not None]
        wins = [r for r in rs if r > 0]
        losses = [r for r in rs if r <= 0]
        gross_win = sum(wins)
        gross_loss = abs(sum(losses))

        peak, max_dd = 1.0, 0.0
        for _, eq in equity_curve:
            peak = max(peak, eq)
            max_dd = min(max_dd, eq / peak - 1.0)

        by_hour: dict[int, list[float]] = {}
        for t in trades:
            if t.result_r is None:
                continue
            hour = datetime.fromisoformat(t.entry_time).hour
            by_hour.setdefault(hour, []).append(t.result_r)

        return {
            "config": {
                "strategy": self._strategy.name,
                "costs": asdict(self._costs),
                "risk_pct_per_trade": self._risk_pct,
                "window_bars": self._window,
                "max_holding_bars": self._max_holding,
            },
            "evaluations": evaluations,
            "signals": signals,
            "trades": len(rs),
            "win_rate": round(len(wins) / len(rs), 4) if rs else None,
            "expectancy_r": round(sum(rs) / len(rs), 4) if rs else None,
            "total_r": round(sum(rs), 3),
            "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
            "avg_win_r": round(sum(wins) / len(wins), 3) if wins else None,
            "avg_loss_r": round(sum(losses) / len(losses), 3) if losses else None,
            "max_drawdown_pct": round(max_dd * 100, 3),
            "final_equity": round(equity_curve[-1][1], 6) if equity_curve else 1.0,
            "exit_reasons": {
                reason: sum(1 for t in trades if t.exit_reason == reason)
                for reason in {t.exit_reason for t in trades if t.exit_reason}
            },
            "mfe_avg_r": round(sum(t.mfe_r for t in trades) / len(trades), 3)
            if trades
            else None,
            "mae_avg_r": round(sum(t.mae_r for t in trades) / len(trades), 3)
            if trades
            else None,
            "by_entry_hour": {
                str(h): {
                    "trades": len(v),
                    "expectancy_r": round(sum(v) / len(v), 3),
                }
                for h, v in sorted(by_hour.items())
            },
            "hold_reasons": dict(
                sorted(hold_reasons.items(), key=lambda kv: kv[1], reverse=True)[:15]
            ),
            "trade_list": [t.to_dict() for t in trades],
            "equity_curve": equity_curve,
        }
