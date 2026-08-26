# -*- coding: utf-8 -*-
"""Клиент MAX Bot API (platform-api2.max.ru).

Токен — заголовок Authorization сырой строкой, без Bearer.
В личке адрес доставки — user_id отправителя, не recipient.chat_id.
"""
from __future__ import annotations

import socket
import ssl
import time
from pathlib import Path
from typing import Any

import requests
import mimetypes
import urllib3.util.connection as urllib3_cn

# На части сетей IPv6 до MAX «висит», curl по IPv4 проходит сразу.
def _ipv4_family():
    return socket.AF_INET


urllib3_cn.allowed_gai_family = _ipv4_family

API_BASE = "https://platform-api2.max.ru"
def _here() -> Path:
    try:
        return Path(__file__).resolve().parent
    except OSError:
        return Path(__file__).parent


CERTS_DIR = _here() / "certs"
BUNDLE_PATH = CERTS_DIR / "ca_bundle.pem"
ROOT_CERT = CERTS_DIR / "russian_trusted_root_ca.cer"
SUB_CERT = CERTS_DIR / "russian_trusted_sub_ca.cer"

# Лимит MAX: не больше 2 сообщений в секунду в один диалог.
_MIN_SEND_INTERVAL = 0.55


class MaxApiError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


def _pem_from_file(path: Path) -> str:
    raw = path.read_bytes()
    if b"BEGIN CERTIFICATE" in raw:
        text = raw.decode("ascii", errors="ignore").strip()
        if not text.endswith("\n"):
            text += "\n"
        return text
    der = ssl.DER_cert_to_PEM_cert(raw)
    if not der.endswith("\n"):
        der += "\n"
    return der


def build_ca_bundle() -> str:
    """Корни Минцифры (+ certifi запасным). Для platform-api2 достаточно RU CA."""
    CERTS_DIR.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    for path in (ROOT_CERT, SUB_CERT):
        if path.is_file():
            parts.append(_pem_from_file(path))
    if not parts:
        try:
            import certifi

            parts.append(Path(certifi.where()).read_text(encoding="ascii"))
        except Exception:
            pass
    if not parts:
        raise MaxApiError("Нет ни certifi, ни сертификатов Минцифры в certs/")
    text = "\n".join(p.strip() for p in parts if p.strip()) + "\n"
    BUNDLE_PATH.write_text(text, encoding="ascii")
    return str(BUNDLE_PATH)




def public_cdn_verify() -> str | bool:
    """CDN MAX (fu.oneme.ru и т.п.) — обычные публичные CA, не корни Минцифры."""
    try:
        import certifi
        return certifi.where()
    except Exception:
        return True


def verify_path() -> str | bool:
    if BUNDLE_PATH.is_file() and BUNDLE_PATH.stat().st_size > 0:
        return str(BUNDLE_PATH)
    try:
        return build_ca_bundle()
    except MaxApiError:
        return True


def callback_button(text: str, payload: str) -> dict:
    return {"type": "callback", "text": text, "payload": payload}


def link_button(text: str, url: str) -> dict:
    return {"type": "link", "text": text, "url": url}


def inline_keyboard(rows: list[list[dict]]) -> dict:
    return {"type": "inline_keyboard", "payload": {"buttons": rows}}


class MaxApi:
    def __init__(self, token: str, *, timeout: float = 35.0):
        token = (token or "").strip()
        if not token:
            raise MaxApiError("Пустой MAX_BOT_TOKEN")
        self.token = token
        self.timeout = timeout
        self._verify = verify_path()
        self._session = requests.Session()
        self._session.headers.update({"Authorization": token})
        self._last_send_at: dict[str, float] = {}

    def _throttle(self, dest_key: str) -> None:
        now = time.monotonic()
        wait = _MIN_SEND_INTERVAL - (now - self._last_send_at.get(dest_key, 0.0))
        if wait > 0:
            time.sleep(wait)
        self._last_send_at[dest_key] = time.monotonic()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        timeout: float | None = None,
    ) -> Any:
        url = f"{API_BASE}{path}"
        wait = timeout if timeout is not None else self.timeout
        if isinstance(wait, (int, float)):
            wait = (8.0, float(wait))
        headers = {"Content-Type": "application/json"} if json is not None else None
        try:
            resp = self._session.request(
                method,
                url,
                params=params,
                json=json,
                headers=headers,
                timeout=wait,
                verify=self._verify,
            )
        except requests.RequestException as exc:
            raise MaxApiError(f"Сеть MAX API: {exc}") from exc
        if resp.status_code == 401:
            raise MaxApiError(
                "401: токен не принят. Нужен сырой Authorization, без Bearer.",
                status=401,
                body=_safe_json(resp),
            )
        if resp.status_code >= 400:
            raise MaxApiError(
                f"MAX API {resp.status_code}: {resp.text[:500]}",
                status=resp.status_code,
                body=_safe_json(resp),
            )
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}

    def get_me(self) -> dict:
        return self._request("GET", "/me")

    def set_commands(self, commands: list[dict]) -> dict:
        return self._request("PATCH", "/me/commands", json={"commands": commands})

    def get_updates(
        self,
        *,
        marker: int | None = None,
        timeout: int = 30,
        limit: int = 100,
        types: list[str] | None = None,
    ) -> dict:
        params: dict[str, Any] = {"timeout": timeout, "limit": limit}
        if marker is not None:
            params["marker"] = marker
        if types:
            params["types"] = ",".join(types)
        # Long poll: ждать до timeout+запас
        return self._request(
            "GET",
            "/updates",
            params=params,
            timeout=timeout + 15,
        )

    def send_message(
        self,
        *,
        user_id: int | None = None,
        chat_id: int | None = None,
        text: str = "",
        attachments: list[dict] | None = None,
        format: str = "html",
        notify: bool = True,
    ) -> dict:
        if user_id:
            params = {"user_id": int(user_id)}
            dest = f"u:{user_id}"
        elif chat_id:
            params = {"chat_id": int(chat_id)}
            dest = f"c:{chat_id}"
        else:
            raise MaxApiError("Нужен user_id (личка) или chat_id (группа)")
        self._throttle(dest)
        body: dict[str, Any] = {"text": text or "", "format": format, "notify": notify}
        if attachments:
            body["attachments"] = attachments
        return self._request("POST", "/messages", params=params, json=body)

    def edit_message(
        self,
        message_id: str,
        *,
        text: str | None = None,
        attachments: list[dict] | None = None,
        format: str = "html",
    ) -> dict:
        body: dict[str, Any] = {"format": format}
        if text is not None:
            body["text"] = text
        if attachments is not None:
            body["attachments"] = attachments
        return self._request("PUT", "/messages", params={"message_id": message_id}, json=body)

    def answer_callback(
        self,
        callback_id: str,
        *,
        notification: str | None = None,
        message: dict | None = None,
    ) -> dict:
        body: dict[str, Any] = {}
        if notification:
            body["notification"] = notification
        if message is not None:
            body["message"] = message
        return self._request(
            "POST",
            "/answers",
            params={"callback_id": callback_id},
            json=body or {"notification": "OK"},
        )

    def request_upload_url(self, file_type: str = "file") -> dict:
        return self._request("POST", "/uploads", params={"type": file_type})

    def upload_and_send_file(
        self,
        path: str | Path,
        *,
        user_id: int | None = None,
        chat_id: int | None = None,
        caption: str = "",
        attachments_extra: list[dict] | None = None,
        file_type: str = "file",
    ) -> dict:
        path = Path(path)
        meta = self.request_upload_url(file_type)
        upload_url = meta.get("url")
        if not upload_url:
            raise MaxApiError(f"POST /uploads не вернул url: {meta}")
        # CDN: без MIME у multipart-части — 403 "There is no file in request"
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as fh:
            up = requests.post(
                upload_url,
                files={"data": (path.name, fh, mime)},
                timeout=120,
                verify=public_cdn_verify(),
            )
        if up.status_code >= 400:
            raise MaxApiError(f"Загрузка файла {up.status_code}: {up.text[:400]}", status=up.status_code)
        payload = up.json() if up.content else {}
        token = payload.get("token") or meta.get("token")
        if not token:
            raise MaxApiError(f"Нет token после загрузки: {payload}")
        # Файл может ещё обрабатываться.
        time.sleep(0.8)
        file_att = {"type": file_type, "payload": {"token": token}}
        atts = [file_att]
        if attachments_extra:
            atts.extend(attachments_extra)
        last_exc: Exception | None = None
        for delay in (0.0, 1.5, 3.0):
            if delay:
                time.sleep(delay)
            try:
                return self.send_message(
                    user_id=user_id,
                    chat_id=chat_id,
                    text=caption,
                    attachments=atts,
                )
            except MaxApiError as exc:
                last_exc = exc
                if exc.status == 400 and "not.ready" in str(exc).lower():
                    continue
                raise
        raise last_exc or MaxApiError("Не удалось отправить файл")

    def download_bytes(self, url: str) -> bytes:
        if not url:
            raise MaxApiError("Пустой URL вложения")
        # CDN: без Authorization бота + публичные CA (не корни Минцифры от platform-api2)
        try:
            resp = requests.get(url, timeout=120, verify=public_cdn_verify())
        except requests.RequestException as exc:
            raise MaxApiError(f"Скачивание вложения: {exc}") from exc
        if resp.status_code >= 400:
            raise MaxApiError(
                f"Скачивание вложения {resp.status_code}: {resp.text[:300]}",
                status=resp.status_code,
            )
        return resp.content



def _safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return resp.text


def dest_from_update(update: dict) -> tuple[int | None, int | None]:
    """(user_id, chat_id). Для лички достаточно user_id."""
    utype = update.get("update_type") or ""
    if utype == "message_callback":
        cb = update.get("callback") or {}
        user = cb.get("user") or {}
        user_id = user.get("user_id") or user.get("id")
        msg = update.get("message") or {}
        rec = msg.get("recipient") or {}
        chat_id = rec.get("chat_id")
        return user_id, chat_id
    if utype == "bot_started":
        chat = update.get("chat") or {}
        user = update.get("user") or {}
        return user.get("user_id") or user.get("id"), chat.get("chat_id")
    msg = update.get("message") or {}
    sender = msg.get("sender") or {}
    rec = msg.get("recipient") or {}
    user_id = (
        sender.get("user_id")
        or sender.get("id")
        or (msg.get("from_user") or {}).get("user_id")
        or (msg.get("from_user") or {}).get("id")
        or update.get("user_id")
        or (update.get("user") or {}).get("user_id")
    )
    chat_id = rec.get("chat_id") or (msg.get("recipient") or {}).get("chat_id")
    return user_id, chat_id


def text_from_update(update: dict) -> str:
    msg = update.get("message") or {}
    body = msg.get("body") or {}
    return (body.get("text") or "").strip()


def attachments_from_update(update: dict) -> list[dict]:
    msg = update.get("message") or {}
    body = msg.get("body") or {}
    atts = body.get("attachments") or []
    return atts if isinstance(atts, list) else []


def callback_payload(update: dict) -> str:
    cb = update.get("callback") or {}
    return (cb.get("payload") or "").strip()


def callback_id(update: dict) -> str:
    cb = update.get("callback") or {}
    return str(cb.get("callback_id") or "")


def sender_name(update: dict) -> tuple[str, str, str]:
    """first, last, username — MAX часто отдаёт только name."""
    utype = update.get("update_type") or ""
    if utype == "message_callback":
        user = (update.get("callback") or {}).get("user") or {}
    elif utype == "bot_started":
        user = update.get("user") or {}
    else:
        user = ((update.get("message") or {}).get("sender") or {})
    name = (user.get("name") or "").strip()
    username = (user.get("username") or "").strip()
    parts = name.split(None, 1)
    first = parts[0] if parts else ""
    last = parts[1] if len(parts) > 1 else ""
    return first, last, username
