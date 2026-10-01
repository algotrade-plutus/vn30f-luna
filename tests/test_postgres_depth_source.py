from datetime import datetime, timedelta
from decimal import Decimal

from plutus.market.adapters.depth import SideAvailability, Truncation
from plutus.market.session import DataField

from src.adapters.data.postgres_depth_source import PostgresDepthSource


class _Pool:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute_query(self, sql, params):
        self.calls.append((sql, params))
        table = next(name for name in self.rows if f"quote.{name}" in sql)
        return self.rows[table]


def _rows():
    return {
        "bidprice": [
            (datetime(2024, 1, 2, 9, 0, 1), 1, Decimal("1100.0")),
            (datetime(2024, 1, 2, 9, 0, 2), 2, Decimal("1099.9")),
            (datetime(2024, 1, 2, 9, 0, 3), 3, Decimal("1099.8")),
            (datetime(2024, 1, 2, 9, 0, 8), 1, Decimal("1100.1")),
        ],
        "askprice": [
            (datetime(2024, 1, 2, 9, 0, 4), 1, Decimal("1100.2")),
            (datetime(2024, 1, 2, 9, 0, 4), 2, Decimal("1100.3")),
            (datetime(2024, 1, 2, 9, 0, 4), 3, Decimal("1100.4")),
        ],
        "bidsize": [
            (datetime(2024, 1, 2, 9, 0, 1), 1, 20),
            (datetime(2024, 1, 2, 9, 0, 2), 2, 30),
            (datetime(2024, 1, 2, 9, 0, 3), 3, 40),
        ],
        "asksize": [
            (datetime(2024, 1, 2, 9, 0, 4), 1, 50),
            (datetime(2024, 1, 2, 9, 0, 4), 2, 60),
            (datetime(2024, 1, 2, 9, 0, 4), 3, 70),
        ],
    }


def test_reconstructs_each_level_independently_and_caches_ticker_day():
    pool = _Pool(_rows())
    source = PostgresDepthSource(pool)
    stamp = datetime(2024, 1, 2, 9, 0, 10)

    book = source.book_at("VN30F2401", stamp, max_age=timedelta(seconds=15))
    again = source.book_at("VN30F2401", stamp, max_age=timedelta(seconds=15))

    assert book.bid.availability is SideAvailability.OBSERVED
    assert [level.price for level in book.bid.levels] == [
        Decimal("1100.1"),
        Decimal("1099.9"),
        Decimal("1099.8"),
    ]
    assert [level.size for level in book.bid.levels] == [20, 30, 40]
    assert book.ask.total_size == 180
    assert DataField.BOOK_SIZE not in book.withheld
    assert again == book
    assert len(pool.calls) == 4
    assert all("datetime >=" in sql and "datetime <=" in sql for sql, _ in pool.calls)


def test_staleness_drops_outward_from_first_old_level():
    pool = _Pool(_rows())
    source = PostgresDepthSource(pool)
    stamp = datetime(2024, 1, 2, 9, 0, 20)

    book = source.book_at("VN30F2401", stamp, max_age=timedelta(seconds=15))

    # Bid level 1's price is fresh enough, but its last size is 19 seconds old.
    assert book.bid.availability is SideAvailability.ABSENT
    assert book.bid.truncation is Truncation.MAX_AGE
    assert book.bid.truncated_at_depth == 1
    # The ask's first level is 16 seconds old and is also refused.
    assert book.ask.availability is SideAvailability.ABSENT
    assert DataField.BOOK in book.withheld
    assert DataField.BOOK_SIZE in book.withheld
