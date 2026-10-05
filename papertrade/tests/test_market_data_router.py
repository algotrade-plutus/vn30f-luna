from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from algotrade_adapter.market_data import (
    PostgresSpotMarketDataClient,
    SplitMarketDataClient,
    build_market_data,
)


class FakeClient:
    def __init__(self, *, query_result=None):
        self.query_result = query_result
        self.subscriptions = []
        self.started = 0
        self.stopped = 0
        self.closed = 0

    async def subscribe(self, instrument, callback):
        self.subscriptions.append((instrument, callback))

    async def start(self):
        self.started += 1

    async def stop(self):
        self.stopped += 1

    async def close(self):
        self.closed += 1

    async def query(self, instrument):
        return self.query_result, instrument


class SplitMarketDataClientTests(unittest.TestCase):
    def test_routes_spot_to_redis_and_futures_to_kafka(self):
        kafka = FakeClient(query_result="kafka")
        redis = FakeClient(query_result="redis")
        router = SplitMarketDataClient(
            kafka_client=kafka,
            spot_client=redis,
            spot_symbol="HSX:VN30",
        )

        async def exercise():
            callback = lambda *_: None
            await router.subscribe("HNXDS:VN30F2609", callback)
            await router.subscribe("HSX:VN30", callback)
            await router.start()
            spot = await router.query("HSX:VN30")
            future = await router.query("HNXDS:VN30F2609")
            await router.stop()
            return spot, future

        spot, future = asyncio.run(exercise())
        self.assertEqual([item[0] for item in kafka.subscriptions], ["HNXDS:VN30F2609"])
        self.assertEqual([item[0] for item in redis.subscriptions], ["HSX:VN30"])
        self.assertEqual(spot, ("redis", "HSX:VN30"))
        self.assertEqual(future, ("kafka", "HNXDS:VN30F2609"))
        self.assertEqual(kafka.started, 1)
        self.assertEqual(kafka.stopped, 1)
        self.assertEqual(redis.stopped, 1)

    def test_kafka_mode_preserves_single_client(self):
        with patch.dict(
            os.environ,
            {
                "PAPERBROKER_KAFKA_BOOTSTRAP_SERVERS": "broker",
                "PAPERBROKER_KAFKA_USERNAME": "user",
                "PAPERBROKER_KAFKA_PASSWORD": "password",
                "PAPERBROKER_ENV_ID": "real",
                "VN30_SPOT_SOURCE": "kafka",
            },
        ), patch("algotrade_adapter.market_data.KafkaMarketDataClient", return_value=FakeClient()) as factory:
            client = build_market_data(spot_symbol="HSX:VN30")
        self.assertIsInstance(client, FakeClient)
        factory.assert_called_once()

    def test_redis_mode_requires_host(self):
        with patch.dict(
            os.environ,
            {
                "PAPERBROKER_KAFKA_BOOTSTRAP_SERVERS": "broker",
                "PAPERBROKER_KAFKA_USERNAME": "user",
                "PAPERBROKER_KAFKA_PASSWORD": "password",
                "PAPERBROKER_ENV_ID": "real",
                "VN30_SPOT_SOURCE": "redis",
            },
            clear=True,
        ), patch("algotrade_adapter.market_data.KafkaMarketDataClient", return_value=FakeClient()):
            with self.assertRaisesRegex(ValueError, "MARKET_REDIS_HOST"):
                build_market_data(spot_symbol="HSX:VN30")

    def test_redis_mode_builds_split_client(self):
        with patch.dict(
            os.environ,
            {
                "PAPERBROKER_KAFKA_BOOTSTRAP_SERVERS": "broker",
                "PAPERBROKER_KAFKA_USERNAME": "user",
                "PAPERBROKER_KAFKA_PASSWORD": "password",
                "PAPERBROKER_ENV_ID": "real",
                "VN30_SPOT_SOURCE": "redis",
                "MARKET_REDIS_HOST": "redis.internal",
                "MARKET_REDIS_PORT": "6380",
                "MARKET_REDIS_DB": "2",
                "MARKET_REDIS_PASSWORD": "redis-password",
            },
        ), patch("algotrade_adapter.market_data.KafkaMarketDataClient", return_value=FakeClient()), patch(
            "algotrade_adapter.market_data.RedisMarketDataClient", return_value=FakeClient()
        ) as redis_factory:
            client = build_market_data(spot_symbol="HSX:VN30")
        self.assertIsInstance(client, SplitMarketDataClient)
        self.assertEqual(client.spot_source, "redis")
        redis_factory.assert_called_once_with(
            host="redis.internal",
            port=6380,
            db=2,
            password="redis-password",
            merge_updates=True,
        )

    def test_postgres_mode_builds_split_client(self):
        with patch.dict(
            os.environ,
            {
                "PAPERBROKER_KAFKA_BOOTSTRAP_SERVERS": "broker",
                "PAPERBROKER_KAFKA_USERNAME": "user",
                "PAPERBROKER_KAFKA_PASSWORD": "password",
                "PAPERBROKER_ENV_ID": "real",
                "VN30_SPOT_SOURCE": "postgres",
                "VN30_PG_HOST": "api.algotrade.vn",
                "VN30_PG_PORT": "5432",
                "VN30_PG_DATABASE": "algotradeDB",
                "VN30_PG_USER": "read-only",
                "VN30_PG_PASSWORD": "secret",
            },
            clear=True,
        ), patch("algotrade_adapter.market_data.KafkaMarketDataClient", return_value=FakeClient()):
            client = build_market_data(spot_symbol="HSX:VN30")
        self.assertIsInstance(client, SplitMarketDataClient)
        self.assertEqual(client.spot_source, "postgres")
        self.assertEqual(client.spot_client.ticker_symbol, "VN30")

    def test_postgres_query_localizes_market_timestamp(self):
        class Cursor:
            def execute(self, query, params):
                self.params = params

            def fetchone(self):
                return datetime(2026, 9, 14, 9, 30), Decimal("1936.69")

        class Connection:
            def __init__(self):
                self.cursor_obj = Cursor()
                self.closed = False

            def cursor(self):
                return self.cursor_obj

            def close(self):
                self.closed = True

        connection = Connection()

        class DBAPI:
            @staticmethod
            def connect(**kwargs):
                self.assertEqual(kwargs["host"], "api.algotrade.vn")
                self.assertTrue(kwargs["ssl_context"])
                return connection

        class PG:
            dbapi = DBAPI

        client = PostgresSpotMarketDataClient(
            host="api.algotrade.vn",
            port=5432,
            database="algotradeDB",
            user="read-only",
            password="secret",
            spot_symbol="HSX:VN30",
        )
        with patch("algotrade_adapter.market_data._load_pg8000", return_value=PG):
            quote = asyncio.run(client.query("HSX:VN30"))
        self.assertIsNotNone(quote)
        self.assertEqual(quote.latest_matched_price, 1936.69)
        self.assertEqual(quote.raw_data["ticker"], "VN30")
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
