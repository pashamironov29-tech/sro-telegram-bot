#!/usr/bin/env python3
# Debug GigaChat OAuth — print status/body only, never credentials.
import os
import sys
import uuid

import requests

os.chdir("/opt/sro-bot")
sys.path.insert(0, "/opt/sro-bot")

from config_keys import GIGACHAT_CREDENTIALS, GIGACHAT_SCOPE

cred = (GIGACHAT_CREDENTIALS or "").strip()
scope = (GIGACHAT_SCOPE or "GIGACHAT_API_PERS").strip()
print("cred_len", len(cred), "looks_basic_b64", cred.endswith("=") or len(cred) > 40)
print("scope", scope)

url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
headers = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "application/json",
    "RqUID": str(uuid.uuid4()),
    "Authorization": f"Basic {cred}",
}
r = requests.post(url, headers=headers, data={"scope": scope}, timeout=30, verify=False)
print("status", r.status_code)
print("body", (r.text or "")[:500])
