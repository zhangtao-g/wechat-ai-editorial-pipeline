#!/usr/bin/env python3
"""WeChat Official Account credential loader.

Credentials are read from the environment first, then from a JSON file
outside the repository. Values are never printed, logged or written back.

Environment
-----------
WECHAT_APPID            公众号 AppID
WECHAT_APPSECRET        公众号 AppSecret
WECHAT_CREDENTIALS_FILE 可选，默认 ~/.hermes/wechat_credentials.json

JSON file shape::

    {"appid": "wx...", "appsecret": "..."}
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_DIR = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


def default_file() -> Path:
    return DEFAULT_DIR.expanduser() / "wechat_credentials.json"


def load() -> tuple[str, str]:
    appid = os.environ.get("WECHAT_APPID", "").strip()
    secret = os.environ.get("WECHAT_APPSECRET", "").strip()
    if appid and secret:
        return appid, secret

    path = Path(os.environ.get("WECHAT_CREDENTIALS_FILE", str(default_file()))).expanduser()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"cannot read credential file {path}: {type(exc).__name__}") from exc
        appid = str(data.get("appid") or "").strip()
        secret = str(data.get("appsecret") or data.get("secret") or "").strip()

    if not appid or not secret:
        raise SystemExit(
            "WeChat credentials missing. Set WECHAT_APPID/WECHAT_APPSECRET, "
            f"or create {path} with {{\"appid\": \"wx...\", \"appsecret\": \"...\"}}"
        )
    return appid, secret


def access_token(timeout: int = 25) -> str:
    """Fetch a fresh access_token (valid ~2h). Never include it in logs."""
    import requests

    appid, secret = load()
    response = requests.get(
        "https://api.weixin.qq.com/cgi-bin/token",
        params={"grant_type": "client_credential", "appid": appid, "secret": secret},
        timeout=timeout,
    )
    data = json.loads(response.content.decode("utf-8"))
    if "access_token" not in data:
        raise SystemExit("access_token request failed: errcode=%s" % data.get("errcode"))
    return data["access_token"]


if __name__ == "__main__":
    # Diagnostics only: print whether credentials resolve, never the values.
    appid, secret = load()
    print(json.dumps({"ok": True, "appid_prefix": appid[:4] + "***", "secret_len": len(secret)}))
