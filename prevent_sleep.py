"""Windows: не уводить ПК в сон, пока работает процесс бота."""

import atexit
import sys

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


def _set_state(flags: int) -> None:
    if sys.platform != "win32":
        return
    import ctypes

    ctypes.windll.kernel32.SetThreadExecutionState(flags)


def enable() -> None:
    _set_state(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)


def disable() -> None:
    _set_state(_ES_CONTINUOUS)


def install_for_bot() -> bool:
    """Включить блокировку сна до выхода процесса. True — если Windows."""
    if sys.platform != "win32":
        return False
    enable()
    atexit.register(disable)
    return True
