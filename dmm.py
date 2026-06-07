"""dmm-radar poller: fetch verified death pins from dmmradar.com and post to Discord."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_URL = "https://dmmradar.com/map/__data.json"
MAP_URL = "https://dmmradar.com/map"
STATE_FILE = Path(os.environ.get("STATE_FILE", "/app/data/seen.json"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "45"))
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
USER_AGENT = "dmm-radar-discord/0.1 (+https://github.com/fenneh)"
WATCH_TTL = timedelta(hours=int(os.environ.get("WATCH_TTL_HOURS", "12")))

TEAM_COLORS = {
    "odablock_team": 0xE67E22,
    "framed_team": 0x3498DB,
    "westham_team": 0x8E44AD,
    "dino_team": 0x27AE60,
    "rhys_team": 0xE74C3C,
    "purpp_team": 0x9B59B6,
}


def fetch_payload() -> dict:
    req = urllib.request.Request(DATA_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def expand(idx, data, seen=None):
    """Walk SvelteKit devalue dedup payload starting at index idx."""
    if not isinstance(idx, int):
        return idx
    if idx < 0:
        return None
    seen = seen or set()
    if idx in seen:
        return None
    seen = seen | {idx}
    val = data[idx]
    if isinstance(val, dict):
        return {k: expand(v, data, seen) if isinstance(v, int) else v for k, v in val.items()}
    if isinstance(val, list):
        return [expand(v, data, seen) if isinstance(v, int) else v for v in val]
    return val


def get_state() -> tuple[list[dict], dict[str, dict]]:
    payload = fetch_payload()
    node = next(n for n in payload["nodes"] if isinstance(n, dict) and "data" in n and isinstance(n["data"], list) and isinstance(n["data"][0], dict) and "deathPins" in n["data"][0])
    root = expand(0, node["data"])
    teams = {t["id"]: t for t in (root.get("teams") or [])}
    return root.get("deathPins") or [], teams


def load_state() -> dict[str, dict]:
    if not STATE_FILE.exists():
        return {}
    try:
        raw = json.loads(STATE_FILE.read_text())
    except Exception:
        return {}
    if isinstance(raw, list):
        return {pid: {"status": "done"} for pid in raw}
    return raw


def save_state(state: dict[str, dict]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if len(state) > 5000:
        state = dict(list(state.items())[-5000:])
    STATE_FILE.write_text(json.dumps(state))


def is_expired(created_at: str | None) -> bool:
    if not created_at:
        return False
    try:
        return datetime.fromisoformat(created_at) < datetime.now(timezone.utc) - WATCH_TTL
    except ValueError:
        return False


def build_embed(pin: dict, teams: dict[str, dict]) -> dict:
    killer = pin.get("killer") or {}
    victim = pin.get("victim") or {}
    killer_name = killer.get("name") or "Unknown"
    victim_name = victim.get("name") or "Unknown"
    killer_team = teams.get(killer.get("team_id") or "", {})
    victim_team = teams.get(victim.get("team_id") or "", {})

    color = TEAM_COLORS.get(killer_team.get("slug") or "", 0x95A5A6)

    def fmt(name: str, team: dict) -> str:
        t = team.get("name")
        return f"**{name}** ({t})" if t else f"**{name}**"

    desc_lines = [f"{fmt(killer_name, killer_team)} killed {fmt(victim_name, victim_team)}"]
    confirmations = pin.get("confirmations")
    if confirmations is not None:
        desc_lines.append(f"`{pin.get('status')}` · {confirmations} confirmations")

    embed = {
        "title": f"{killer_name} → {victim_name}",
        "url": MAP_URL,
        "description": "\n".join(desc_lines),
        "color": color,
        "timestamp": pin.get("created_at"),
        "footer": {"text": "dmmradar.com"},
    }
    killer_img = killer.get("image_url")
    if killer_img:
        embed["thumbnail"] = {"url": f"https://dmmradar.com{killer_img}"}
    return embed


def post_webhook(payload: dict) -> None:
    if not WEBHOOK_URL:
        raise SystemExit("DISCORD_WEBHOOK_URL not set")
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        if r.status >= 300:
            raise RuntimeError(f"discord webhook returned {r.status}: {r.read()[:300]!r}")


def pick_clip_urls(pin: dict) -> list[str]:
    urls = [c["url"] for c in (pin.get("clips") or []) if c.get("url")]
    twitch = [u for u in urls if "twitch.tv" in u]
    return twitch if twitch else urls


def post_clips(urls: list[str]) -> None:
    for url in urls:
        time.sleep(0.4)
        post_webhook({"content": url})


def post_pin(pin: dict, teams: dict[str, dict]) -> list[str]:
    post_webhook({"embeds": [build_embed(pin, teams)]})
    urls = pick_clip_urls(pin)
    post_clips(urls)
    return urls


def is_postable(pin: dict) -> bool:
    return pin.get("status") == "verified"


def run_once(state: dict[str, dict]) -> dict[str, dict]:
    pins, teams = get_state()
    pins_by_id = {p["id"]: p for p in pins}

    new_pins = [p for p in pins if p["id"] not in state and is_postable(p)]
    new_pins.sort(key=lambda p: p.get("created_at") or "")

    watching = [pid for pid, v in state.items() if v.get("status") == "watching"]
    verified_total = sum(1 for p in pins if is_postable(p))
    print(
        f"[{time.strftime('%H:%M:%S')}] poll: pins={len(pins)} verified={verified_total} "
        f"new={len(new_pins)} watching={len(watching)} state={len(state)}",
        flush=True,
    )

    for p in new_pins:
        urls = post_pin(p, teams)
        if urls:
            state[p["id"]] = {"status": "done"}
        else:
            state[p["id"]] = {"status": "watching", "created_at": p.get("created_at")}
        save_state(state)
        time.sleep(0.8)

    for pid in watching:
        entry = state[pid]
        if is_expired(entry.get("created_at")):
            state[pid] = {"status": "done"}
            save_state(state)
            continue
        pin = pins_by_id.get(pid)
        if not pin:
            continue
        urls = pick_clip_urls(pin)
        if not urls:
            continue
        print(f"[{time.strftime('%H:%M:%S')}] clip arrived for {pid}: {len(urls)} url(s)", flush=True)
        post_clips(urls)
        state[pid] = {"status": "done"}
        save_state(state)
        time.sleep(0.8)

    return state


def cmd_preview(n: int = 3) -> None:
    pins, teams = get_state()
    verified = [p for p in pins if is_postable(p)]
    verified.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    sample = list(reversed(verified[:n]))
    print(f"total pins: {len(pins)}, verified: {len(verified)}, sending {len(sample)} to preview webhook")
    for p in sample:
        post_pin(p, teams)
        time.sleep(0.8)
    print("done")


def cmd_loop() -> None:
    state = load_state()
    if not state:
        print("first run — seeding state with existing pins (won't post backlog)", flush=True)
        pins, _ = get_state()
        state = {p["id"]: {"status": "done"} for p in pins if is_postable(p)}
        save_state(state)
    while True:
        try:
            state = run_once(state)
        except Exception as e:
            print(f"poll error: {e!r}", flush=True)
        time.sleep(POLL_INTERVAL)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "loop"
    if cmd == "preview":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        cmd_preview(n)
    elif cmd == "loop":
        cmd_loop()
    elif cmd == "dump":
        pins, _ = get_state()
        print(json.dumps(pins[:3], indent=2))
    else:
        raise SystemExit(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
