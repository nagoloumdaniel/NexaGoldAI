"""Async MetaTrader 5 client (compte démo ou réel).

Le paquet Python `MetaTrader5` est un pont IPC **synchrone** vers un terminal
MT5 qui tourne localement (Windows uniquement). Chaque appel est donc exécuté
dans un thread (`asyncio.to_thread`) et sérialisé derrière un verrou pour que
le moteur async ne bloque jamais et que le terminal ne reçoive qu'un appel à
la fois.

Les réponses sont normalisées vers les formes que le reste du moteur attend
déjà (héritées du client Capital.com) : unités signées en entrée, bougies
`{time, open, high, low, close, volume}` en sortie — changer de broker ne
touche ni la stratégie ni le risque.

Particularités MT5 :
- le volume s'exprime en **lots** (1 lot XAUUSD = `trade_contract_size` onces,
  généralement 100). La conversion unités <-> lots se fait ici, à la frontière.
- les timestamps sont en **heure du serveur du broker** (souvent UTC+2/+3, pas
  UTC). `MT5_UTC_OFFSET_HOURS` permet de les ramener en UTC pour rester
  cohérent avec l'historique Dukascopy stocké en base.
- pas de "guaranteed stop" : `get_market_rules` renvoie toujours
  `guaranteed_stop_allowed=False`.
"""

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone

from app.config import Settings

try:  # Le paquet n'existe que sous Windows ; ailleurs le moteur démarre sans broker.
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - chemin Linux/Mac uniquement
    mt5 = None

logger = logging.getLogger("nexagold.mt5")

# Identifiant "magic" attaché à tous les ordres du bot : permet de distinguer
# les positions NexaGold des positions manuelles sur le même compte.
MAGIC = 20260725


class BrokerError(Exception):
    """Raised when the MetaTrader 5 terminal returns an error."""


def _timeframes() -> dict:
    return {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D": mt5.TIMEFRAME_D1,
        "W": mt5.TIMEFRAME_W1,
    }


def _deal_source(reason: int) -> str:
    """MT5 deal reason -> labels que le moteur utilisait déjà (SL/TP/USER...)."""
    mapping = {
        mt5.DEAL_REASON_SL: "SL",
        mt5.DEAL_REASON_TP: "TP",
        mt5.DEAL_REASON_SO: "CLOSE_OUT",
        mt5.DEAL_REASON_EXPERT: "SYSTEM",
        mt5.DEAL_REASON_CLIENT: "USER",
        mt5.DEAL_REASON_MOBILE: "USER",
        mt5.DEAL_REASON_WEB: "USER",
    }
    return mapping.get(reason, "SYSTEM")


class MT5Client:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._lock = asyncio.Lock()
        self._connected = False
        # Cache des symbol_info (contract size, digits...) par symbole.
        self._symbol_info_cache: dict[str, dict] = {}

    # -- Cycle de vie ---------------------------------------------------------

    async def close(self) -> None:
        if mt5 is None or not self._connected:
            return
        async with self._lock:
            await asyncio.to_thread(mt5.shutdown)
            self._connected = False

    async def _call(self, func, *args, **kwargs):
        """Sérialise un appel MT5 : connexion garantie puis exécution en thread."""
        if mt5 is None:
            raise BrokerError(
                "Paquet MetaTrader5 indisponible (Windows uniquement) : "
                "le moteur de trading doit tourner nativement sous Windows"
            )
        async with self._lock:
            await asyncio.to_thread(self._ensure_connected_sync)
            return await asyncio.to_thread(func, *args, **kwargs)

    def _ensure_connected_sync(self) -> None:
        if self._connected:
            info = mt5.terminal_info()
            if info is not None and info.connected:
                return
            logger.warning("Terminal MT5 déconnecté — tentative de reconnexion")
            mt5.shutdown()
            self._connected = False

        s = self._settings
        kwargs: dict = {"timeout": 30_000}
        # En mode rattachement, ne pas passer les identifiants : le terminal
        # garde (ou rouvre) la session du compte qui y est déjà connecté.
        if not s.mt5_attach and s.mt5_login.strip():
            kwargs.update(
                login=int(s.mt5_login),
                password=s.mt5_password,
                server=s.mt5_server,
            )
        path = s.mt5_terminal_path.strip()
        ok = mt5.initialize(path, **kwargs) if path else mt5.initialize(**kwargs)
        if not ok:
            raise BrokerError(f"initialize -> {mt5.last_error()}")
        self._connected = True
        # Rendre visibles les symboles utilisés (sinon copy_rates échoue).
        for symbol in {s.symbol, s.mt5_macro_symbol} - {""}:
            if not mt5.symbol_select(symbol, True):
                logger.warning("Symbole %s introuvable chez ce broker", symbol)
        account = mt5.account_info()
        if account is not None:
            logger.info(
                "MT5 connecté : compte %s (%s), serveur %s",
                account.login,
                "démo" if account.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO else "RÉEL",
                account.server,
            )

    # -- Conversion de temps --------------------------------------------------
    # MT5 renvoie des epochs exprimés en heure serveur du broker. On les ramène
    # en UTC via l'offset configuré pour rester alignés avec la base.

    def _server_epoch_to_utc(self, epoch: float) -> datetime:
        dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
        return dt - timedelta(hours=self._settings.mt5_utc_offset_hours)

    def _utc_to_server(self, dt: datetime) -> datetime:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt + timedelta(hours=self._settings.mt5_utc_offset_hours)

    def _candle_time(self, epoch: float) -> str:
        # Format naïf "YYYY-MM-DDTHH:MM:SS", identique à l'ancien client.
        return self._server_epoch_to_utc(epoch).strftime("%Y-%m-%dT%H:%M:%S")

    # -- Infos symbole --------------------------------------------------------

    def _symbol_info_sync(self, symbol: str) -> dict:
        info = mt5.symbol_info(symbol)
        if info is None:
            raise BrokerError(f"symbol_info({symbol}) -> {mt5.last_error()}")
        data = {
            "digits": int(info.digits),
            "point": float(info.point),
            "stops_level_points": float(info.trade_stops_level),
            "contract_size": float(info.trade_contract_size) or 1.0,
            "volume_min": float(info.volume_min),
            "volume_max": float(info.volume_max),
            "volume_step": float(info.volume_step) or 0.01,
            "filling_mode": int(info.filling_mode),
            "trade_mode": int(info.trade_mode),
        }
        self._symbol_info_cache[symbol] = data
        return data

    async def get_symbol_info(self, symbol: str | None = None) -> dict:
        symbol = symbol or self._settings.symbol
        return await self._call(self._symbol_info_sync, symbol)

    # -- Données de marché ----------------------------------------------------

    def _price_sync(self, symbol: str) -> dict:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise BrokerError(f"symbol_info_tick({symbol}) -> {mt5.last_error()}")
        info = self._symbol_info_sync(symbol)
        # Marché considéré tradable si le symbole autorise le trading et que le
        # dernier tick est récent (sinon week-end / marché fermé).
        tick_age = abs(
            (datetime.now(timezone.utc) - self._server_epoch_to_utc(tick.time)).total_seconds()
        )
        tradeable = info["trade_mode"] == mt5.SYMBOL_TRADE_MODE_FULL and tick_age < 600
        return {
            "instrument": symbol,
            "time": self._candle_time(tick.time),
            "bid": float(tick.bid),
            "ask": float(tick.ask),
            "tradeable": tradeable,
        }

    async def get_price(self, symbol: str | None = None) -> dict:
        """Dernier bid/ask d'un instrument (défaut : le symbole configuré)."""
        return await self._call(self._price_sync, symbol or self._settings.symbol)

    async def get_market_rules(self, symbol: str | None = None) -> dict:
        """Règles de trading normalisées (distance de stop mini, décimales...).

        Les distances sont exprimées en fraction du prix, comme avant, pour que
        le Trader n'ait pas à connaître la convention points/pips de MT5.
        """
        symbol = symbol or self._settings.symbol

        def _rules() -> dict:
            info = self._symbol_info_sync(symbol)
            tick = mt5.symbol_info_tick(symbol)
            mid = (float(tick.bid) + float(tick.ask)) / 2 if tick else 0.0
            min_stop_pct = (
                info["stops_level_points"] * info["point"] / mid if mid else 0.0
            )
            return {
                # MT5 n'a pas de guaranteed stop — le Trader le désactive seul.
                "guaranteed_stop_allowed": False,
                "min_guaranteed_stop_pct": 0.0,
                "min_stop_pct": min_stop_pct,
                "decimal_places": info["digits"],
                "contract_size": info["contract_size"],
                "volume_min": info["volume_min"],
                "volume_max": info["volume_max"],
                "volume_step": info["volume_step"],
            }

        return await self._call(_rules)

    def _candles_from_rates(self, rates) -> list[dict]:
        if rates is None:
            raise BrokerError(f"copy_rates -> {mt5.last_error()}")
        return [
            {
                "time": self._candle_time(float(r["time"])),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": int(r["tick_volume"]),
                "complete": True,
            }
            for r in rates
        ]

    async def get_candles(
        self,
        symbol: str | None = None,
        granularity: str = "M1",
        count: int = 200,
    ) -> list[dict]:
        """Dernières bougies OHLCV (la plus récente, en cours, incluse)."""
        symbol = symbol or self._settings.symbol
        timeframe = _timeframes().get(granularity) if mt5 else None

        def _fetch():
            tf = timeframe
            if tf is None:
                raise BrokerError(f"Granularité inconnue: {granularity}")
            return mt5.copy_rates_from_pos(symbol, tf, 0, min(count, 5000))

        return self._candles_from_rates(await self._call(_fetch))

    async def get_candles_range(
        self,
        granularity: str,
        start: datetime,
        end: datetime,
        symbol: str | None = None,
    ) -> list[dict]:
        """Bougies OHLCV entre deux timestamps UTC (backfill historique)."""
        symbol = symbol or self._settings.symbol

        def _fetch():
            tf = _timeframes().get(granularity)
            if tf is None:
                raise BrokerError(f"Granularité inconnue: {granularity}")
            return mt5.copy_rates_range(
                symbol,
                tf,
                self._utc_to_server(start),
                self._utc_to_server(end),
            )

        return self._candles_from_rates(await self._call(_fetch))

    # -- Compte ---------------------------------------------------------------

    async def get_account_summary(self) -> dict:
        """Snapshot normalisé du compte, consommé par /account et les rapports."""

        def _account() -> dict:
            account = mt5.account_info()
            if account is None:
                raise BrokerError(f"account_info -> {mt5.last_error()}")
            positions = mt5.positions_get() or []
            return {
                "balance": float(account.balance),
                "nav": float(account.equity),
                "currency": account.currency,
                "open_trade_count": len(positions),
                "unrealized_pl": float(account.profit),
                "is_demo": account.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO,
                "login": int(account.login),
                "server": account.server,
            }

        return await self._call(_account)

    # -- Ordres / positions ---------------------------------------------------

    def _units_to_volume(self, units: float, info: dict) -> float:
        """Unités (onces) -> volume en lots, arrondi au pas du broker."""
        lots = abs(units) / info["contract_size"]
        step = info["volume_step"]
        lots = math.floor(lots / step + 1e-9) * step
        lots = round(lots, 8)
        if lots < info["volume_min"]:
            raise BrokerError(
                f"Volume calculé {lots} lot(s) sous le minimum broker "
                f"{info['volume_min']} (risque trop faible pour ce compte)"
            )
        return min(lots, info["volume_max"])

    @staticmethod
    def _filling_mode(info: dict) -> int:
        if info["filling_mode"] & mt5.SYMBOL_FILLING_IOC:
            return mt5.ORDER_FILLING_IOC
        if info["filling_mode"] & mt5.SYMBOL_FILLING_FOK:
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_RETURN

    @staticmethod
    def _position_id_from_deal(deal_ticket: int) -> int | None:
        deals = mt5.history_deals_get(ticket=deal_ticket)
        if deals:
            return int(deals[0].position_id)
        return None

    async def create_market_order(
        self,
        units: float,
        symbol: str | None = None,
        stop_loss_price: float | None = None,
        take_profit_price: float | None = None,
        decimals: int = 2,
    ) -> dict:
        """Ordre au marché. Unités positives = achat, négatives = vente.

        Le moteur raisonne en unités signées (onces) ; la conversion en lots
        MT5 et le sens BUY/SELL se font ici. Le SL/TP est attaché à la position
        côté serveur, donc il survit à un arrêt du bot.
        """
        symbol = symbol or self._settings.symbol

        def _send() -> dict:
            info = self._symbol_info_sync(symbol)
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                raise BrokerError(f"symbol_info_tick({symbol}) -> {mt5.last_error()}")
            volume = self._units_to_volume(units, info)
            is_buy = units > 0
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
                "price": float(tick.ask if is_buy else tick.bid),
                "deviation": 20,
                "magic": MAGIC,
                "comment": "NexaGold",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._filling_mode(info),
            }
            if stop_loss_price is not None:
                request["sl"] = round(stop_loss_price, info["digits"])
            if take_profit_price is not None:
                request["tp"] = round(take_profit_price, info["digits"])

            result = mt5.order_send(request)
            if result is None:
                raise BrokerError(f"order_send -> {mt5.last_error()}")
            if result.retcode not in (
                mt5.TRADE_RETCODE_DONE,
                mt5.TRADE_RETCODE_DONE_PARTIAL,
            ):
                raise BrokerError(
                    f"order_send -> retcode {result.retcode}: {result.comment}"
                )
            position_id = None
            if result.deal:
                position_id = self._position_id_from_deal(int(result.deal))
            reference = str(position_id or result.order or result.deal)
            executed_units = float(result.volume) * info["contract_size"]
            return {
                "dealReference": reference,
                "dealStatus": "ACCEPTED",
                "level": float(result.price),
                "volume_lots": float(result.volume),
                "size": executed_units,
                "affectedDeals": [{"dealId": reference}],
            }

        return await self._call(_send)

    async def get_deal_confirmation(self, deal_reference: str) -> dict:
        """Compat : la référence renvoyée par `create_market_order` est déjà le
        ticket de position MT5 ; on la renvoie telle quelle."""
        return {
            "dealStatus": "ACCEPTED",
            "affectedDeals": [{"dealId": str(deal_reference)}],
        }

    async def get_open_positions(
        self, symbol: str | None = None, magic: int | None = None
    ) -> list[dict]:
        """Positions ouvertes, filtrables par symbole et par magic number.

        Le Trader passe (symbol, MAGIC) pour ne compter que les positions du
        bot : une position manuelle (ou sur un autre instrument) ne doit ni
        consommer le quota MAX_OPEN_POSITIONS ni être fermée par le moteur.
        """

        def _positions() -> list[dict]:
            positions = (
                mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
            )
            if positions is None:
                raise BrokerError(f"positions_get -> {mt5.last_error()}")
            account = mt5.account_info()
            currency = account.currency if account else None
            out = []
            for p in positions:
                if magic is not None and int(getattr(p, "magic", 0)) != magic:
                    continue
                entry = p._asdict()
                info = self._symbol_info_cache.get(p.symbol) or self._symbol_info_sync(
                    p.symbol
                )
                entry["units"] = float(p.volume) * info["contract_size"]
                entry["currency"] = currency
                out.append(entry)
            return out

        return await self._call(_positions)

    @staticmethod
    def normalise_position(entry: dict) -> dict:
        """Aplati une position MT5 pour la réconciliation et l'API."""
        is_buy = entry.get("type") == 0  # POSITION_TYPE_BUY
        return {
            "deal_id": str(entry.get("ticket")),
            "deal_reference": str(entry.get("identifier") or entry.get("ticket")),
            "instrument": entry.get("symbol"),
            "direction": "BUY" if is_buy else "SELL",
            "size": float(entry.get("units") or 0),
            "open_level": float(entry.get("price_open") or 0),
            "pnl": float(entry.get("profit") or 0),
            "currency": entry.get("currency"),
        }

    async def find_close_event(
        self,
        position_id: str,
        opened_at: datetime | None,
        side: str,
    ) -> dict | None:
        """Cherche dans l'historique MT5 le deal de clôture d'une position.

        Renvoie `{exit_price, closed_at, source}` ou None si la position n'a
        pas (encore) de clôture prouvée — le Trader reste alors conservateur.
        """

        def _find() -> dict | None:
            start = self._utc_to_server(
                (opened_at or datetime.now(timezone.utc) - timedelta(days=30))
                - timedelta(hours=1)
            )
            end = self._utc_to_server(datetime.now(timezone.utc) + timedelta(hours=1))
            deals = mt5.history_deals_get(start, end, position=int(position_id))
            if not deals:
                return None
            closing_type = mt5.DEAL_TYPE_SELL if side == "BUY" else mt5.DEAL_TYPE_BUY
            closures = [
                d
                for d in deals
                if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY)
                and d.type == closing_type
            ]
            if not closures:
                return None
            last = max(closures, key=lambda d: d.time)
            return {
                "exit_price": float(last.price),
                "closed_at": self._server_epoch_to_utc(last.time),
                "source": _deal_source(int(last.reason)),
            }

        try:
            return await self._call(_find)
        except (ValueError, BrokerError) as exc:
            logger.warning("Historique MT5 illisible pour position=%s: %s", position_id, exc)
            return None

    async def close_position_by_deal_id(self, deal_id: str) -> dict:
        """Ferme exactement une position (jamais tout l'instrument)."""
        if not deal_id:
            raise ValueError("deal_id is required")

        def _close() -> dict:
            positions = mt5.positions_get(ticket=int(deal_id))
            if not positions:
                raise BrokerError(f"Position {deal_id} introuvable sur le terminal")
            position = positions[0]
            info = self._symbol_info_sync(position.symbol)
            tick = mt5.symbol_info_tick(position.symbol)
            if tick is None:
                raise BrokerError(
                    f"symbol_info_tick({position.symbol}) -> {mt5.last_error()}"
                )
            is_buy_position = position.type == mt5.POSITION_TYPE_BUY
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": position.symbol,
                "volume": float(position.volume),
                "type": mt5.ORDER_TYPE_SELL if is_buy_position else mt5.ORDER_TYPE_BUY,
                "position": int(position.ticket),
                "price": float(tick.bid if is_buy_position else tick.ask),
                "deviation": 20,
                "magic": MAGIC,
                "comment": "NexaGold close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._filling_mode(info),
            }
            result = mt5.order_send(request)
            if result is None:
                raise BrokerError(f"order_send (close) -> {mt5.last_error()}")
            if result.retcode not in (
                mt5.TRADE_RETCODE_DONE,
                mt5.TRADE_RETCODE_DONE_PARTIAL,
            ):
                raise BrokerError(
                    f"order_send (close) -> retcode {result.retcode}: {result.comment}"
                )
            return {
                "dealReference": str(result.deal or result.order),
                "dealStatus": "ACCEPTED",
                "level": float(result.price),
                "date": datetime.now(timezone.utc).isoformat(),
            }

        return await self._call(_close)

    async def close_position(self, symbol: str | None = None) -> dict:
        """Ferme toutes les positions ouvertes sur un symbole."""
        symbol = symbol or self._settings.symbol
        closed = []
        for entry in await self.get_open_positions():
            if entry.get("symbol") == symbol:
                closed.append(
                    await self.close_position_by_deal_id(str(entry["ticket"]))
                )
        return {"closed": closed}
