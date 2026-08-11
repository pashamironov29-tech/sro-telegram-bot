"""Доступ к конфиденциальному телефонному справочнику."""

import importlib
import json
import os

import config_keys

ACCESS_FILE = os.path.join(os.path.dirname(__file__), "contacts_access.json")

_verified_ids: set[int] = set()
_pending_ids: set[int] = set()
_contacts_mode_users: set[int] = set()


def _current_password() -> str:
    """Читает пароль из config_keys.py с диска (актуально после сохранения файла)."""
    config_path = os.path.join(os.path.dirname(__file__), "config_keys.py")
    try:
        with open(config_path, encoding="utf-8") as file:
            for line in file:
                stripped = line.strip()
                if stripped.startswith("CONTACTS_PASSWORD"):
                    _, _, raw = stripped.partition("=")
                    return raw.strip().strip('"').strip("'")
    except OSError:
        pass
    importlib.reload(config_keys)
    return (getattr(config_keys, "CONTACTS_PASSWORD", "") or "").strip()


def _load_verified():
    global _verified_ids
    if not os.path.isfile(ACCESS_FILE):
        return
    try:
        with open(ACCESS_FILE, encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, list):
            _verified_ids = {int(chat_id) for chat_id in data}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        _verified_ids = set()


def _save_verified():
    try:
        with open(ACCESS_FILE, "w", encoding="utf-8") as file:
            json.dump(sorted(_verified_ids), file)
    except OSError:
        pass


_load_verified()


def is_protected() -> bool:
    return bool(_current_password())


def is_verified(chat_id: int) -> bool:
    if not is_protected():
        return True
    return chat_id in _verified_ids


def is_pending(chat_id: int) -> bool:
    return chat_id in _pending_ids


def start_password_prompt(chat_id: int) -> None:
    _pending_ids.add(chat_id)


def cancel_pending(chat_id: int) -> None:
    _pending_ids.discard(chat_id)


def verify_password(chat_id: int, password: str) -> bool:
    if not is_protected():
        return True
    if password.strip() == _current_password():
        _verified_ids.add(chat_id)
        _pending_ids.discard(chat_id)
        _save_verified()
        return True
    return False


def password_not_configured() -> bool:
    return not is_protected()


def enter_contacts_mode(chat_id: int) -> None:
    _contacts_mode_users.add(chat_id)


def exit_contacts_mode(chat_id: int) -> None:
    _contacts_mode_users.discard(chat_id)


def is_contacts_mode(chat_id: int) -> bool:
    return chat_id in _contacts_mode_users
