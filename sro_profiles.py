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

# Канонические сайты — явный список (не «тихий» откат на ОГПС).
EXPECTED_SITE_BY_SRO: dict[str, str] = {
    "OGPS": "https://www.srogen.ru",
    "MOTS": "https://www.sro-mots.ru",
    "OSO": "https://srooso.ru",
    "NOSO": "https://www.sronoso.ru",
    "OSOES": "https://assrtm.ru",
    "OSOT": "https://nup-sro.ru",
    "SOVS": "https://www.msro-sibir.ru",
    "OGPO": "https://sroogpo.ru",
    "GPS": "https://sro-gps.ru",
    "OGPP": "https://www.srosp.ru",
    "SPROF": "https://sprofproekt.ru",
    "OPP": "https://np-pspz.ru",
    "PRIIS": "https://sro-priis.ru",
    "MGEO": "https://sroigeo.ru",
    "GEOIND": "https://www.srogeo.ru",
}

PROD_SRO_COUNT = 15

ACTIVITY_LABEL = {
    "stroy": "строители",
    "proekt": "проектировщики",
    "izysk": "изыскания",
}

# Полные профили для ВСЕХ партнёрских СРО.
# Раньше пилот был только ОГПС/ОГПП/ОСО — из‑за этого казалось, что «в боте 3 СРО».
_PROFILES: dict[str, dict] = {
    "OGPS": {
        "id": "OGPS",
        "name": "ОГПС",
        "short_title": "Ассоциация «ГЕН» (ОГПС)",
        "activity": "stroy",
        "site": EXPECTED_SITE_BY_SRO["OGPS"],
        "voprosy_url": EXPECTED_SITE_BY_SRO["OGPS"] + "/voprosy/",
    },
    "MOTS": {
        "id": "MOTS",
        "name": "МОТС",
        "short_title": "МОТС",
        "activity": "stroy",
        "site": EXPECTED_SITE_BY_SRO["MOTS"],
        "voprosy_url": EXPECTED_SITE_BY_SRO["MOTS"] + "/voprosy/",
    },
    "OSO": {
        "id": "OSO",
        "name": "ОСО",
        "short_title": "ОСО",
        "activity": "stroy",
        "site": EXPECTED_SITE_BY_SRO["OSO"],
        "voprosy_url": EXPECTED_SITE_BY_SRO["OSO"] + "/voprosy/",
    },
    "NOSO": {
        "id": "NOSO",
        "name": "НОСО",
        "short_title": "НОСО",
        "activity": "stroy",
        "site": EXPECTED_SITE_BY_SRO["NOSO"],
        "voprosy_url": EXPECTED_SITE_BY_SRO["NOSO"] + "/voprosy/",
    },
    "OSOES": {
        "id": "OSOES",
        "name": "ОСОЕС",
        "short_title": "ОСОЕС",
        "activity": "stroy",
        "site": EXPECTED_SITE_BY_SRO["OSOES"],
        "voprosy_url": EXPECTED_SITE_BY_SRO["OSOES"] + "/voprosy/",
    },
    "OSOT": {
        "id": "OSOT",
        "name": "ОСОТ",
        "short_title": "ОСОТ",
        "activity": "stroy",
        "site": EXPECTED_SITE_BY_SRO["OSOT"],
        "voprosy_url": EXPECTED_SITE_BY_SRO["OSOT"] + "/voprosy/",
    },
    "SOVS": {
        "id": "SOVS",
        "name": "ОСОВС",
        "short_title": "ОСОВС",
        "activity": "stroy",
        "site": EXPECTED_SITE_BY_SRO["SOVS"],
        "voprosy_url": EXPECTED_SITE_BY_SRO["SOVS"] + "/voprosy/",
    },
    "OGPO": {
        "id": "OGPO",
        "name": "ОГПО",
        "short_title": "ОГПО",
        "activity": "proekt",
        "site": EXPECTED_SITE_BY_SRO["OGPO"],
        "voprosy_url": EXPECTED_SITE_BY_SRO["OGPO"] + "/voprosy/",
    },
    "GPS": {
        "id": "GPS",
        "name": "ГПС",
        "short_title": "ГПС",
        "activity": "stroy",
        "site": EXPECTED_SITE_BY_SRO["GPS"],
        "voprosy_url": EXPECTED_SITE_BY_SRO["GPS"] + "/voprosy/",
    },
    "OGPP": {
        "id": "OGPP",
        "name": "ОГПП",
        "short_title": "ГрадСтройПроект (ОГПП)",
        "activity": "proekt",
        "site": EXPECTED_SITE_BY_SRO["OGPP"],
        "voprosy_url": EXPECTED_SITE_BY_SRO["OGPP"] + "/voprosy/",
    },
    "SPROF": {
        "id": "SPROF",
        "name": "СПРОФ",
        "short_title": "СПРОФ",
        "activity": "proekt",
        "site": EXPECTED_SITE_BY_SRO["SPROF"],
        "voprosy_url": EXPECTED_SITE_BY_SRO["SPROF"] + "/voprosy/",
    },
    "OPP": {
        "id": "OPP",
        "name": "ОПП",
        "short_title": "ОПП",
        "activity": "proekt",
        "site": EXPECTED_SITE_BY_SRO["OPP"],
        "voprosy_url": EXPECTED_SITE_BY_SRO["OPP"] + "/voprosy/",
    },
    "PRIIS": {
        "id": "PRIIS",
        "name": "ПРИИС",
        "short_title": "ПРИИС",
        "activity": "izysk",
        "site": EXPECTED_SITE_BY_SRO["PRIIS"],
        "voprosy_url": EXPECTED_SITE_BY_SRO["PRIIS"] + "/voprosy/",
    },
    "MGEO": {
        "id": "MGEO",
        "name": "МГЕО",
        "short_title": "МГЕО",
        "activity": "izysk",
        "site": EXPECTED_SITE_BY_SRO["MGEO"],
        "voprosy_url": EXPECTED_SITE_BY_SRO["MGEO"] + "/voprosy/",
    },
    "GEOIND": {
        "id": "GEOIND",
        "name": "ГеоИндустрия",
        "short_title": "ГеоИндустрия",
        "activity": "izysk",
        "site": EXPECTED_SITE_BY_SRO["GEOIND"],
        "voprosy_url": EXPECTED_SITE_BY_SRO["GEOIND"] + "/voprosy/",
    },
}

_DEFAULT_GEN = _PROFILES["OGPS"]


def _norm_site(url: str) -> str:
    return (url or "").rstrip("/").lower().replace("://www.", "://")


def site_base_for_sro(sro_id: str | None) -> str:
    """Базовый URL сайта СРО (без /reestr/)."""
    if not sro_id:
        return _DEFAULT_GEN["site"]
    if sro_id in _PROFILES:
        return _PROFILES[sro_id]["site"]
    if sro_id in EXPECTED_SITE_BY_SRO:
        return EXPECTED_SITE_BY_SRO[sro_id]
    try:
        from reestr_sync import SRO_SOURCES

        src = SRO_SOURCES.get(sro_id)
        if src and src.get("list_url"):
            parsed = urlparse(src["list_url"])
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        pass
    # Не подменяем чужой СРО сайтом ОГПС — иначе «всё ведёт на srogen.ru».
    return ""


def assert_prod_sro_ready() -> None:
    """Жёсткая проверка перед боем: ровно 15 СРО, у каждого свой сайт."""
    ids = list_known_sro_ids()
    if len(ids) != PROD_SRO_COUNT:
        raise RuntimeError(
            f"PROD GATE: ожидалось {PROD_SRO_COUNT} СРО, в SRO_ACTIVITY={len(ids)}: {ids}"
        )
    missing_prof = [s for s in ids if s not in _PROFILES]
    if missing_prof:
        raise RuntimeError(f"PROD GATE: нет полного профиля для {missing_prof}")
    missing_exp = [s for s in ids if s not in EXPECTED_SITE_BY_SRO]
    if missing_exp:
        raise RuntimeError(f"PROD GATE: нет EXPECTED_SITE для {missing_exp}")
    seen_hosts: dict[str, str] = {}
    for sid in ids:
        site = site_base_for_sro(sid)
        exp = EXPECTED_SITE_BY_SRO[sid]
        if not site:
            raise RuntimeError(f"PROD GATE: пустой сайт для {sid}")
        if _norm_site(site) != _norm_site(exp):
            raise RuntimeError(f"PROD GATE: сайт {sid}={site}, ожидалось {exp}")
        host = _norm_site(site)
        if host in seen_hosts and seen_hosts[host] != sid:
            raise RuntimeError(
                f"PROD GATE: одинаковый сайт у {seen_hosts[host]} и {sid}: {site}"
            )
        seen_hosts[host] = sid
        if sid != "OGPS" and _norm_site(site) == _norm_site(EXPECTED_SITE_BY_SRO["OGPS"]):
            raise RuntimeError(f"PROD GATE: {sid} внезапно на сайте ОГПС")


def _profile_for(sro_id: str) -> dict:
    activity = SRO_ACTIVITY.get(sro_id, "stroy")
    site = site_base_for_sro(sro_id)
    if sro_id in _PROFILES:
        base = dict(_PROFILES[sro_id])
        base["site"] = site or base.get("site") or ""
        base["voprosy_url"] = base.get("voprosy_url") or (f"{site}/voprosy/" if site else "")
        return base
    from reestr_sync import sro_display_name

    name = sro_display_name(sro_id)
    return {
        "id": sro_id,
        "name": name,
        "short_title": name,
        "activity": activity,
        "site": site,
        "voprosy_url": f"{site}/voprosy/" if site else "",
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