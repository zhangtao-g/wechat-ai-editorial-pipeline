#!/usr/bin/env python3
"""Cron entry point for news collection.

Three modes mirror the production schedules:

  hot       AIHOT + domestic sources, every 20 minutes
  fallback  20:00 quality fallback
  daily     daily digest at 08:02

The collector (`ai_news.py`) runs inside the isolated Horizon virtualenv
because Horizon pins a different pydantic version than the agent runtime.
PYTHONPATH is stripped for the child process on purpose.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


def env_without_pythonpath() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}


def horizon_python() -> str:
    return os.environ.get("HORIZON_PYTHON", str(HERMES_HOME / "tools/Horizon/.venv/bin/python"))


def daily_cover() -> Path:
    stamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    cover = HERMES_HOME / "workspace/drafts" / f"daily-cover-{stamp}.png"
    renderer = Path(
        os.environ.get(
            "DAILY_COVER_RENDERER",
            str(HERMES_HOME / "workspace/covers/daily/render_daily_cover.py"),
        )
    )
    result = subprocess.run(
        [sys.executable, str(renderer), "--out", str(cover)],
        capture_output=True,
        text=True,
        timeout=60,
        env=env_without_pythonpath(),
    )
    if result.returncode:
        print(json.dumps({"ok": False, "error": "daily_cover_generation_failed"}))
        raise SystemExit(1)
    return cover


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["hot", "fallback", "daily"], required=True)
    args = parser.parse_args()

    env = env_without_pythonpath()
    payload: dict = {}
    if args.mode == "daily":
        payload["cover_path"] = str(daily_cover())

    result = subprocess.run(
        [horizon_python(), str(HERE / "ai_news.py"), args.mode],
        capture_output=True,
        text=True,
        timeout=105,
        env=env,
    )
    if result.returncode:
        print(result.stderr[-1500:], file=sys.stderr)
        return result.returncode

    if result.stdout.strip():
        payload.update(json.loads(result.stdout))
    elif args.mode == "daily":
        payload.update({"mode": "daily", "candidates": [], "minimum_items": 10})

    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
