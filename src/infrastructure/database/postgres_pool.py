"""Infrastructure: PostgreSQL connection pool for algotradeDB.
Enforces datetime index constraint on all queries.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import logging
from typing import Any, Iterator

import psycopg2
from psycopg2 import pool

from ..config.env_config import DatabaseConfig

logger = logging.getLogger(__name__)


class PostgresConnectionPool:
    """Connection pool for algotradeDB."""

    def __init__(self, config: DatabaseConfig | None = None, min_conn: int = 1, max_conn: int = 5) -> None:
        self.config = config or DatabaseConfig()
        self._pool: pool.SimpleConnectionPool | None = None
        self.min_conn = min_conn
        self.max_conn = max_conn

    def connect(self) -> None:
        if self._pool is None:
            self._pool = pool.SimpleConnectionPool(
                self.min_conn,
                self.max_conn,
                host=self.config.host,
                port=self.config.port,
                dbname=self.config.database,
                user=self.config.user,
                password=self.config.password,
                connect_timeout=10,
                application_name="calibrum_research_read_only",
                options="-c default_transaction_read_only=on -c statement_timeout=300000",
            )
            logger.info("Postgres connection pool established to %s:%s", self.config.host, self.config.port)

    def close(self) -> None:
        if self._pool is not None:
            self._pool.closeall()
            self._pool = None

    @contextmanager
    def get_connection(self) -> Iterator[Any]:
        if self._pool is None:
            self.connect()
        conn = self._pool.getconn()
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

    def execute_query(self, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        """Execute a parameterized query and return rows.
        Guards that SQL contains datetime bounding to avoid full table scans.
        """
        sql_lower = sql.lower()
        if "datetime" not in sql_lower or ">=" not in sql_lower or "<=" not in sql_lower:
            raise ValueError(
                "Postgres index rule violation: Query MUST contain both 'datetime >= ...' and 'datetime <= ...' "
                "to activate the btree(datetime, tickersymbol) primary index."
            )
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()
