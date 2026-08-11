"""Профили партнёрских СРО: сайт, тип деятельности, ссылки для ИИ/FAQ."""

from __future__ import annotations

from urllib.parse import urlparse

# stroy — НОСТРОЙ; proekt — НОПРИЗ проектирование; izysk — НОПРИЗ изыскания
SRO_ACTIVITY = {
    "OGPS": "stroy",
    "MOTS": "stroy",
    "OSO": "stroy",
    "NOSO": "stroy",
    "OSOES": "stroy",
    "OSOT": "stroy",
    "SOVS": "stroy",
    "OGPO": "proekt",
    "GPS": "stroy",
    "OGPP": "proekt",
    "SPROF": "proekt",
    "OPP": "proekt",
    "PRIIS": "izysk",
    "MGEO": "izysk",
    "GEOIND": "izysk",
}

ACTIVITY_LABEL = {
    "stroy": "строители",
    "proekt": "проектировщики",
    "izysk": "изыскания",
}

# Пилот: полные профили (имя/заголовок); сайт для всех — из реестра / site_base_for_sro
_PROFILES: dict[str, dict] = {
    "OGPS": {
        "id": "OGPS",
        "name": "ОГПС",
        "short_title": "Ассоциация «ГЕН» (ОГПС)",
        "activity": "stroy",
        "site": "https://www.srogen.ru",
        "voprosy_url": "https://www.srogen.ru/voprosy/",
    },
    "OGPP": {
        "id": "OGPP",
        "name": "ОГПП",
        "short_title": "ГрадСтройПроект (ОГПП)",
        "activity": "proekt",
        "site": "https://www.srosp.ru",
        "voprosy_url": "https://www.srosp.ru/voprosy/",
    },
    "OSO": {
        "id": "OSO",
        "name": "ОСО",
        "short_title": "ОСО",
        "activity": "stroy",
        "site": "https://srooso.ru",
        "voprosy_url": "https://srooso.ru/voprosy/",
    },
}

_DEFAULT_GEN = _PROFILES["OGPS"]


def site_base_for_sro(sro_id: str | None) -> str:
    """Базовый URL сайта СРО (без /reestr/)."""
    if not sro_id:
        return _DEFAULT_GEN["site"]
    if sro_id in _PROFILES:
        return _PROFILES[sro_id]["site"]
    try:
        from reestr_sync import SRO_SOURCES

        src = SRO_SOURCES.get(sro_id)
        if src and src.get("list_url"):
            parsed = urlparse(src["list_url"])
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        pass
    return _DEFAULT_GEN["site"]


def _profile_for(sro_id: str) -> dict:
    activity = SRO_ACTIVITY.get(sro_id, "stroy")
    site = site_base_for_sro(sro_id)
    if sro_id in _PROFILES:
        base = dict(_PROFILES[sro_id])
        base["site"] = site
        base["voprosy_url"] = base.get("voprosy_url") or f"{site}/voprosy/"
        return base
    from reestr_sync import sro_display_name

    name = sro_display_name(sro_id)
    return {
        "id": sro_id,
        "name": name,
        "short_title": name,
        "activity": activity,
        "site": site,
        "voprosy_url": f"{site}/voprosy/",
    }


def get_sro_profile(sro_id: str | None) -> dict | None:
    if not sro_id:
        return None
    if sro_id in SRO_ACTIVITY or sro_id in _PROFILES:
        return _profile_for(sro_id)
    return None


def list_known_sro_ids() -> list[str]:
    return list(SRO_ACTIVITY.keys())


def activity_allows_scopes(activity: str | None, scopes: list[str]) -> bool:
    if not scopes or "common" in scopes:
        return True
    if not activity:
        return True
    return activity in scopes


def format_activity_line(profile: dict | None) -> str:
    if not profile:
        return ""
    act = ACTIVITY_LABEL.get(profile["activity"], profile["activity"])
    return f"{profile['short_title']} · {act}"
