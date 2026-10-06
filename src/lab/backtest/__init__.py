"""Local, lightweight standard backtest engine."""

from .config import BacktestConfig
from .evaluator import evaluate
from .metrics import BacktestMetrics
from .positions import PositionStreamRecorder, position_stream_from_commands
from .result import BacktestResult
from .stream import validate_position_stream

__all__ = [
    "BacktestConfig",
    "BacktestMetrics",
    "BacktestResult",
    "PositionStreamRecorder",
    "position_stream_from_commands",
    "evaluate",
    "validate_position_stream",
]
