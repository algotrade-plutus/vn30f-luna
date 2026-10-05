"""Production PaperTrade runtime for the VN30 calendar alpha."""


def build_calendar_service():
    """Lazy import keeps the pure schedule usable without PaperBroker."""
    from .service import build_calendar_service as factory

    return factory()


__all__ = ["build_calendar_service"]
