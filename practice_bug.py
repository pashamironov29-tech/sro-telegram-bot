"""Учебные поломки бота — только если есть локальный practice_bug.local.py (не в git)."""

_active = False


def _bootstrap() -> None:
    global _active
    try:
        import practice_bug_local as loc

        _active = bool(getattr(loc, "PRACTICE_ACTIVE", False))
    except ImportError:
        _active = False


def is_practice_active() -> bool:
    return _active


_bootstrap()
