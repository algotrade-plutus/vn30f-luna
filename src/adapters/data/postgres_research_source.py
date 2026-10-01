"""Read-only PostgreSQL loader for canonical 30-minute research bars."""
from __future__ import annotations

from datetime import date, datetime, time

import pandas as pd

from src.infrastructure.database.postgres_pool import PostgresConnectionPool


def _bounds(start: date, end: date) -> tuple[datetime, datetime]:
    return datetime.combine(start, time.min), datetime.combine(end, time.max)


class PostgresResearchSource:
    """Aggregate tick and volume streams in ``algotradeDB`` without local files."""

    _BUCKET = """
        CASE
          WHEN {alias}.datetime::time < TIME '09:00'
            THEN date_trunc('day', {alias}.datetime) + INTERVAL '9 hours'
          ELSE date_trunc('hour', {alias}.datetime)
             + floor(extract(minute from {alias}.datetime) / 30) * INTERVAL '30 minutes'
        END
    """

    def __init__(self, pool: PostgresConnectionPool | None = None) -> None:
        self.pool = pool or PostgresConnectionPool()

    def load_front_month_bars(self, start: date, end: date) -> pd.DataFrame:
        return self._load_front_month_bars(start, end, minutes=30)

    def load_front_month_bars_5m(
        self,
        start: date,
        end: date,
        *,
        collapse_closing_auction: bool = False,
    ) -> pd.DataFrame:
        """Return front-month 5-minute bars from raw database ticks.

        Signal generation keeps the archived 14:30 boundary and 14:45 ATC
        print separate.  Plutus execution collapses both into one 14:30-14:45
        closing interval so an ATC order is submitted before its fill price is
        observed.
        """

        return self._load_front_month_bars(
            start,
            end,
            minutes=5,
            collapse_closing_auction=collapse_closing_auction,
        )

    def _load_front_month_bars(
        self,
        start: date,
        end: date,
        *,
        minutes: int,
        collapse_closing_auction: bool = False,
    ) -> pd.DataFrame:
        start_dt, end_dt = _bounds(start, end)
        if minutes not in (5, 30):
            raise ValueError(f"Unsupported research bar size: {minutes} minutes")
        price_bucket = self._bucket(
            "m", minutes, collapse_closing_auction=collapse_closing_auction
        )
        volume_bucket = self._bucket(
            "v", minutes, collapse_closing_auction=collapse_closing_auction
        )
        session_filter_price = self._session_filter("m", minutes)
        session_filter_volume = self._session_filter("v", minutes)
        sql = f"""
            WITH price_bars AS (
              SELECT
                {price_bucket} AS bucket,
                m.tickersymbol AS contract,
                (array_agg(m.price ORDER BY m.datetime ASC))[1] AS open,
                max(m.price) AS high,
                min(m.price) AS low,
                (array_agg(m.price ORDER BY m.datetime DESC))[1] AS close
              FROM quote.matched m
              JOIN quote.futurecontractcode f
                ON f.datetime = m.datetime::date
               AND f.tickersymbol = m.tickersymbol
               AND f.datetime >= %s AND f.datetime <= %s
              WHERE m.datetime >= %s AND m.datetime <= %s
                AND f.futurecode = 'VN30F1M'
                {session_filter_price}
              GROUP BY bucket, m.tickersymbol
            ),
            volume_bars AS (
              SELECT
                {volume_bucket} AS bucket,
                v.tickersymbol AS contract,
                sum(v.quantity)::bigint AS volume
              FROM quote.matchedvolume v
              JOIN quote.futurecontractcode f
                ON f.datetime = v.datetime::date
               AND f.tickersymbol = v.tickersymbol
               AND f.datetime >= %s AND f.datetime <= %s
              WHERE v.datetime >= %s AND v.datetime <= %s
                AND f.futurecode = 'VN30F1M'
                {session_filter_volume}
              GROUP BY bucket, v.tickersymbol
            )
            SELECT p.bucket, p.open, p.high, p.low, p.close,
                   coalesce(v.volume, 0), p.contract,
                   r.price, c.price, fl.price
            FROM price_bars p
            LEFT JOIN volume_bars v
              ON v.bucket = p.bucket AND v.contract = p.contract
            LEFT JOIN quote.reference r
              ON r.datetime = p.bucket::date AND r.tickersymbol = p.contract
             AND r.datetime >= %s AND r.datetime <= %s
            LEFT JOIN quote.ceil c
              ON c.datetime = p.bucket::date AND c.tickersymbol = p.contract
             AND c.datetime >= %s AND c.datetime <= %s
            LEFT JOIN quote.floor fl
              ON fl.datetime = p.bucket::date AND fl.tickersymbol = p.contract
             AND fl.datetime >= %s AND fl.datetime <= %s
            ORDER BY p.bucket ASC
        """
        day_args = (start_dt, end_dt)
        rows = self.pool.execute_query(
            sql,
            (*day_args, start_dt, end_dt, *day_args, start_dt, end_dt,
             *day_args, *day_args, *day_args),
        )
        return pd.DataFrame(
            rows,
            columns=[
                "Datetime", "Open", "High", "Low", "Close", "Volume",
                "Contract", "Reference", "Ceiling", "Floor",
            ],
        )

    def load_index_bars(self, start: date, end: date) -> pd.DataFrame:
        return self._load_index_bars(start, end, minutes=30)

    def load_index_bars_5m(
        self,
        start: date,
        end: date,
        *,
        collapse_closing_auction: bool = False,
    ) -> pd.DataFrame:
        return self._load_index_bars(
            start,
            end,
            minutes=5,
            collapse_closing_auction=collapse_closing_auction,
        )

    @classmethod
    def _bucket(
        cls,
        alias: str,
        minutes: int,
        *,
        collapse_closing_auction: bool,
    ) -> str:
        if minutes == 30:
            return cls._BUCKET.format(alias=alias)
        regular_bucket = f"""
            date_trunc('hour', {alias}.datetime)
              + floor(extract(minute from {alias}.datetime) / {minutes})
                * INTERVAL '{minutes} minutes'
        """
        if not collapse_closing_auction:
            return regular_bucket
        return f"""
            CASE
              WHEN {alias}.datetime::time >= TIME '14:30'
                THEN date_trunc('day', {alias}.datetime)
                  + INTERVAL '14 hours 30 minutes'
              ELSE {regular_bucket}
            END
        """

    @staticmethod
    def _session_filter(alias: str, minutes: int) -> str:
        if minutes not in (5, 30):
            raise ValueError(f"Unsupported research bar size: {minutes} minutes")
        return f"""
            AND (({alias}.datetime::time >= TIME '09:00'
                  AND {alias}.datetime::time <= TIME '11:30')
              OR ({alias}.datetime::time >= TIME '13:00'
                  AND {alias}.datetime::time <= TIME '14:45:59.999999'))
        """

    def _load_index_bars(
        self,
        start: date,
        end: date,
        *,
        minutes: int,
        collapse_closing_auction: bool = False,
    ) -> pd.DataFrame:
        start_dt, end_dt = _bounds(start, end)
        if minutes not in (5, 30):
            raise ValueError(f"Unsupported research bar size: {minutes} minutes")
        price_bucket = self._bucket(
            "m", minutes, collapse_closing_auction=collapse_closing_auction
        )
        session_filter = self._session_filter("m", minutes)
        sql = f"""
            SELECT
              {price_bucket} AS bucket,
              (array_agg(m.price ORDER BY m.datetime ASC))[1] AS open,
              max(m.price) AS high,
              min(m.price) AS low,
              (array_agg(m.price ORDER BY m.datetime DESC))[1] AS close,
              count(*)::bigint AS volume
            FROM quote.matched m
            WHERE m.datetime >= %s AND m.datetime <= %s
              AND m.tickersymbol = 'VN30'
              {session_filter}
            GROUP BY bucket
            ORDER BY bucket ASC
        """
        rows = self.pool.execute_query(sql, (start_dt, end_dt))
        return pd.DataFrame(
            rows,
            columns=["Datetime", "Open", "High", "Low", "Close", "Volume"],
        )
