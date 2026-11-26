#!/usr/bin/env python3
"""Post The Division 2 Escalation missions and daily drops to Discord.

Runs from GitHub Actions every 15 minutes during a window. It:
  1. does nothing before START_HOUR (Berlin time) or once today's post is done,
  2. reads the ProtoTrack Target Loot page,
  3. compares missions / drops / caches with the last posted data,
  4. posts to the Discord webhook if they changed, and saves the new state.

Only the Python standard library is used, so the workflow needs no installs.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

SOURCE_URL = "https://prototrack.gg/target-loot/target-loot.php"
TZ = ZoneInfo("Europe/Berlin")
START_HOUR = 10   # first check, Berlin time (your request)
GIVE_UP_HOUR = 16  # last check before giving up for the day (a guess, adjust freely)
STATE_FILE = Path(__file__).parent / "state" / "last_posted.json"
EXPECTED_MISSIONS = 5


# ---------------------------------------------------------------- scraping

class _TextLines(HTMLParser):
    """Turn HTML into a list of visible text lines (one per text node)."""

    SKIP = {"script", "style", "noscript", "template", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._skip:
            return
        text = re.sub(r"\s+", " ", html.unescape(data)).strip()
        if text:
            self.lines.append(text)


def page_lines(raw_html: str) -> list[str]:
    parser = _TextLines()
    parser.feed(raw_html)
    return parser.lines


def _section(lines: list[str], start: str, stops: list[str]) -> list[str]:
    """Lines after the heading containing `start` up to the first `stops` heading."""
    begin = next((i for i, l in enumerate(lines) if start.lower() in l.lower()), None)
    if begin is None:
        return []
    out = []
    for line in lines[begin + 1:]:
        if any(s.lower() in line.lower() for s in stops):
            break
        out.append(line)
    return out


# A row ends with its "last seen" cell, e.g. "7 days ago", "yesterday", "today", "never".
_ROW_END = re.compile(r"(\bago\b|^yesterday$|^today$|^never$|^new$)", re.I)
# Header / filler lines inside the table that are not data.
_NOISE = re.compile(
    r"^(missions?|target loot|loot history|appearances?|last seen|\d+ missions?|"
    r"\d+ selected|daily cache rotation|cache|item)$",
    re.I,
)
_SET_TYPE = re.compile(r"^\(?\s*(brand set|gear set|exotic|named item|weapon|gear)\s*\)?$", re.I)


def _rows(block: list[str]) -> list[list[str]]:
    rows, current = [], []
    for line in block:
        if _NOISE.match(line):
            continue
        current.append(line)
        if _ROW_END.search(line):
            rows.append(current)
            current = []
    return rows


def _clean_row(row: list[str]) -> tuple[str, str, str]:
    """(name, item, kind) from one table row; counts and 'last seen' are dropped."""
    cells = [c for c in row if not _ROW_END.search(c) and not re.fullmatch(r"[\d\s×x]+", c)]
    name = cells[0] if cells else ""
    rest = cells[1:]
    kind = ""
    for c in list(rest):
        m = _SET_TYPE.match(c)
        if m:
            kind = m.group(1).title()
            rest.remove(c)
    item = rest[0] if rest else ""
    # "Gila Guard (brand set)" written in one cell
    m = re.match(r"^(.*?)\s*\((brand set|gear set|exotic|named item)\)$", item, re.I)
    if m:
        item, kind = m.group(1), m.group(2).title()
    return name, item, kind


def parse(raw_html: str) -> dict:
    lines = page_lines(raw_html)
    full = "\n".join(lines)

    missions_block = _section(lines, "Escalation Missions", ["Requisition Vendor"])
    vendor_block = _section(lines, "Requisition Vendor", ["Free from day one", "Help with the daily"])

    missions = [
        {"mission": n, "drop": i, "type": k}
        for n, i, k in (_clean_row(r) for r in _rows(missions_block))
        if n and i
    ]
    caches = [
        {"cache": n, "item": i}
        for n, i, _ in (_clean_row(r) for r in _rows(vendor_block))
        if n and i
    ]

    week = re.search(r"Rotation week\s*(.+)", full)
    updated = re.search(r"Last updated\s*(.+)", full)
    return {
        "missions": missions,
        "caches": caches,
        "week": week.group(1).strip() if week else "",
        "updated": updated.group(1).strip() if updated else "",
    }


def signature(data: dict) -> dict:
    """The part that is compared with the previous post."""
    return {"missions": data["missions"], "caches": data["caches"]}


def fetch() -> str:
    req = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "div2-escalation-discord-bot (GitHub Actions)"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ---------------------------------------------------------------- discord

def discord_payload(data: dict, today: str) -> dict:
    mission_lines = [
        f"**{m['mission']}**\n└ {m['drop']}" + (f" *({m['type']})*" if m["type"] else "")
        for m in data["missions"]
    ]
    fields = [{"name": "Missions & daily drops", "value": "\n".join(mission_lines)[:1024], "inline": False}]
    if data["caches"]:
        fields.append({
            "name": "Requisition vendor caches",
            "value": "\n".join(f"**{c['cache']}**: {c['item']}" for c in data["caches"])[:1024],
            "inline": False,
        })
    footer = "Data: ProtoTrack.gg Target Loot"
    if data["updated"]:
        footer += f" · last updated {data['updated']}"
    return {
        "username": "Escalation",
        "embeds": [{
            "title": f"Escalation · {today}",
            "url": SOURCE_URL,
            "description": f"Rotation week {data['week']}" if data["week"] else None,
            "color": 0xF26722,
            "fields": fields,
            "footer": {"text": footer},
        }],
    }


def post(webhook: str, payload: dict) -> None:
    req = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "div2-escalation-discord-bot"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"Discord returned HTTP {resp.status}")


# ---------------------------------------------------------------- main

def set_output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as fh:
            fh.write(f"{key}={value}\n")


def main() -> int:
    force = os.environ.get("FORCE", "").lower() == "true"
    dry_run = os.environ.get("DRY_RUN", "").lower() == "true"
    now = datetime.now(TZ)
    today = now.strftime("%Y-%m-%d")
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}

    if not force:
        if state.get("posted_on") == today:
            print(f"Already posted today ({today}). Nothing to do.")
            return 0
        if not (START_HOUR <= now.hour <= GIVE_UP_HOUR):
            print(f"{now:%H:%M} Berlin is outside {START_HOUR}:00-{GIVE_UP_HOUR}:59. Nothing to do.")
            return 0

    data = parse(fetch())
    print(json.dumps(data, indent=2, ensure_ascii=False))

    if len(data["missions"]) != EXPECTED_MISSIONS:
        print(f"::error::Expected {EXPECTED_MISSIONS} missions, parsed {len(data['missions'])}. "
              "The page layout may have changed.")
        return 1

    if not force and signature(data) == state.get("signature"):
        print("Data is the same as the last post. Will check again in 15 minutes.")
        if now.hour == GIVE_UP_HOUR and now.minute >= 45:
            print("::warning::Giving up for today: the data never changed.")
        return 0

    payload = discord_payload(data, now.strftime("%a %d %b %Y"))
    if dry_run:
        print("DRY RUN, would post:\n" + json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        print("::error::The DISCORD_WEBHOOK_URL secret is not set.")
        return 1
    post(webhook, payload)
    print("Posted to Discord.")

    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(
        {"posted_on": today, "posted_at": now.isoformat(timespec="minutes"), "signature": signature(data)},
        indent=2, ensure_ascii=False) + "\n")
    set_output("state_changed", "true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
