"""Market-data routing for the PaperTrade runtime.

The trading contract is streamed from Kafka.  The VN30 index driver can be
served by a separate Redis or PostgreSQL feed when the Kafka topic is
unavailable.  Keeping the two clients behind one small facade lets the alpha
framework continue to receive the same ``(instrument, QuoteSnapshot)`` callbacks.
"""

from __future__ import annotations

import os
import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from paperbroker.market_data import KafkaMarketDataClient, RedisMarketDataClient
from paperbroker.market_data import QuoteSnapshot


class SplitMarketDataClient:
    """Route one spot instrument to Redis and all other instruments to Kafka."""

    def __init__(
        self,
        *,
        kafka_client: Any,
        spot_client: Any,
        spot_symbol: str,
    ) -> None:
        if not spot_symbol:
            raise ValueError("spot_symbol is required")
        self.kafka_client = kafka_client
        self.spot_client = spot_client
        self.spot_symbol = spot_symbol
        self.spot_source = str(getattr(spot_client, "spot_source", "redis"))

    async def subscribe(self, instrument: str, callback: Callable[..., None]) -> None:
        client = self.spot_client if instrument == self.spot_symbol else self.kafka_client
        await client.subscribe(instrument, callback)

    async def start(self) -> None:
        spot_start = getattr(self.spot_client, "start", None)
        if spot_start is not None:
            await spot_start()
        start = getattr(self.kafka_client, "start", None)
        if start is not None:
            await start()

    async def stop(self) -> None:
        errors: list[BaseException] = []
        stop = getattr(self.kafka_client, "stop", None)
        if stop is not None:
            try:
                await stop()
            except BaseException as exc:  # preserve cleanup of the second client
                errors.append(exc)
        spot_stop = getattr(self.spot_client, "stop", None)
        spot_close = getattr(self.spot_client, "close", None)
        cleanup = spot_stop or spot_close
        if cleanup is not None:
            try:
                await cleanup()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise errors[0]

    async def query(self, instrument: str) -> Optional[Any]:
        client = self.spot_client if instrument == self.spot_symbol else self.kafka_client
        query = getattr(client, "query", None)
        if query is None:
            return None
        result = query(instrument)
        if hasattr(result, "__await__"):
            return await result
        return result


class PostgresSpotMarketDataClient:
    """Poll the read-only ``quote.matched`` table for a spot index quote.

    The database stores quote timestamps without timezone.  This feed is known
    to use Vietnam local market time, so timestamps are localized to
    ``Asia/Ho_Chi_Minh`` before freshness checks.  A repeated old row is not
    emitted again, which prevents a stale database value from looking live.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        spot_symbol: str,
        ticker_symbol: str = "VN30",
        poll_interval_s: float = 1.0,
        connect_timeout_s: float = 5.0,
    ) -> None:
        if not spot_symbol or not ticker_symbol:
            raise ValueError("spot_symbol and ticker_symbol are required")
        if not 1 <= port <= 65535:
            raise ValueError("VN30_PG_PORT must be in [1, 65535]")
        if not 0.2 <= poll_interval_s <= 30:
            raise ValueError("VN30_PG_POLL_INTERVAL_S must be in [0.2, 30]")
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.spot_symbol = spot_symbol
        self.ticker_symbol = ticker_symbol
        self.poll_interval_s = poll_interval_s
        self.connect_timeout_s = connect_timeout_s
        self.spot_source = "postgres"
        self._callbacks: list[Callable[..., None]] = []
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_key: Optional[tuple[Any, float]] = None

    async def subscribe(self, instrument: str, callback: Callable[..., None]) -> None:
        if instrument != self.spot_symbol:
            raise ValueError(f"Postgres spot client only serves {self.spot_symbol}")
        self._callbacks.append(callback)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def close(self) -> None:
        await self.stop()

    async def query(self, instrument: str) -> Optional[QuoteSnapshot]:
        if instrument != self.spot_symbol:
            return None
        return await asyncio.to_thread(self._query_once)

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                quote = await self.query(self.spot_symbol)
                if quote is not None:
                    key = (quote.timestamp, quote.latest_matched_price)
                    if key != self._last_key:
                        self._last_key = key
                        for callback in tuple(self._callbacks):
                            result = callback(self.spot_symbol, quote)
                            if hasattr(result, "__await__"):
                                await result
            except asyncio.CancelledError:
                raise
            except Exception:
                # The alpha's basis freshness gate remains closed until a
                # successful query produces a new source timestamp.
                pass
            await asyncio.sleep(self.poll_interval_s)

    def _query_once(self) -> Optional[QuoteSnapshot]:
        pg8000 = _load_pg8000()
        connection = pg8000.dbapi.connect(
            user=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.database,
            timeout=self.connect_timeout_s,
            ssl_context=True,
        )
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT datetime, price
                FROM quote.matched
                WHERE tickersymbol = %s
                ORDER BY datetime DESC
                LIMIT 1
                """,
                (self.ticker_symbol,),
            )
            row = cursor.fetchone()
        finally:
            connection.close()
        if not row:
            return None
        observed_at, price = row
        if observed_at.tzinfo is None:
            from zoneinfo import ZoneInfo

            observed_at = observed_at.replace(tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
        observed_at = observed_at.astimezone(timezone.utc)
        return QuoteSnapshot(
            instrument=self.spot_symbol,
            latest_matched_price=float(price),
            timestamp=observed_at.timestamp(),
            datetime_str=observed_at.isoformat(),
            raw_data={
                "source": "postgres",
                "table": "quote.matched",
                "ticker": self.ticker_symbol,
            },
        )


def build_market_data(*, spot_symbol: Optional[str] = None) -> Any:
    """Build the configured market-data client without exposing credentials.

    ``VN30_SPOT_SOURCE=kafka`` preserves the existing all-Kafka behavior.
    ``VN30_SPOT_SOURCE=redis`` routes only ``spot_symbol`` through the Redis
    quote service and keeps execution futures on Kafka.
    """

    kafka_client = KafkaMarketDataClient(
        bootstrap_servers=_required_env("PAPERBROKER_KAFKA_BOOTSTRAP_SERVERS"),
        username=_required_env("PAPERBROKER_KAFKA_USERNAME"),
        password=_required_env("PAPERBROKER_KAFKA_PASSWORD"),
        env_id=_required_env("PAPERBROKER_ENV_ID"),
        auto_offset_reset="latest",
        merge_updates=True,
    )
    source = os.getenv("VN30_SPOT_SOURCE", "kafka").strip().lower()
    if source not in {"kafka", "redis", "postgres"}:
        raise ValueError("VN30_SPOT_SOURCE must be kafka, redis, or postgres")
    if source == "kafka" or spot_symbol is None:
        return kafka_client

    if source == "postgres":
        host = os.getenv("VN30_PG_HOST", "").strip()
        database = os.getenv("VN30_PG_DATABASE", "").strip()
        user = os.getenv("VN30_PG_USER", "").strip()
        password = os.getenv("VN30_PG_PASSWORD", "")
        if not host or not database or not user or not password:
            raise ValueError(
                "VN30_PG_HOST, VN30_PG_DATABASE, VN30_PG_USER, and VN30_PG_PASSWORD "
                "are required when VN30_SPOT_SOURCE=postgres"
            )
        try:
            port = int(os.getenv("VN30_PG_PORT", "5432"))
            poll_interval_s = float(os.getenv("VN30_PG_POLL_INTERVAL_S", "1.0"))
        except ValueError as exc:
            raise ValueError("VN30_PG_PORT and VN30_PG_POLL_INTERVAL_S must be numeric") from exc
        return SplitMarketDataClient(
            kafka_client=kafka_client,
            spot_client=PostgresSpotMarketDataClient(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,
                spot_symbol=spot_symbol,
                ticker_symbol=os.getenv("VN30_PG_TICKER", "VN30").strip() or "VN30",
                poll_interval_s=poll_interval_s,
            ),
            spot_symbol=spot_symbol,
        )

    host = os.getenv("MARKET_REDIS_HOST", "").strip()
    if not host:
        raise ValueError("MARKET_REDIS_HOST is required when VN30_SPOT_SOURCE=redis")
    try:
        port = int(os.getenv("MARKET_REDIS_PORT", "6379"))
        db = int(os.getenv("MARKET_REDIS_DB", "0"))
    except ValueError as exc:
        raise ValueError("MARKET_REDIS_PORT and MARKET_REDIS_DB must be integers") from exc
    if not 1 <= port <= 65535:
        raise ValueError("MARKET_REDIS_PORT must be in [1, 65535]")
    if db < 0:
        raise ValueError("MARKET_REDIS_DB must be non-negative")
    redis_client = RedisMarketDataClient(
        host=host,
        port=port,
        db=db,
        password=os.getenv("MARKET_REDIS_PASSWORD"),
        merge_updates=True,
    )
    return SplitMarketDataClient(
        kafka_client=kafka_client,
        spot_client=redis_client,
        spot_symbol=spot_symbol,
    )


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _load_pg8000() -> Any:
    try:
        import pg8000
    except ImportError as exc:
        raise RuntimeError("pg8000 is required when VN30_SPOT_SOURCE=postgres") from exc
    return pg8000
