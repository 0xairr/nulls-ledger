#!/usr/bin/env python3
"""Collect the NULLS memory-card ledger from public X data (via FxTwitter) into ledger.json.

- awards: every « memory card unlocked » reply by @nullsxyz, with the post that earned it
- quests: every "side quest:" post by @nullsxyz, and who solved it first (and how fast)
- list:   the NULLS LIST count from @nullslist's « PLAYER #N REGISTERED » posts

Incremental: re-run any time (GitHub Actions runs it every ~10 min). Writes ledger.json
only when something changed. Standard library only.
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

FX = "https://api.fxtwitter.com/2"
TEAM, LIST = "nullsxyz", "nullslist"
UA = {"User-Agent": "nulls-ledger/1.0 (fan-made tracker)"}
OUT = Path(__file__).resolve().with_name("ledger.json")
# Memory cards were announced 2026-11-11 18:07 UTC; nothing before this day can be an award.
CARDS_SINCE = int(datetime(2026, 11, 11, tzinfo=timezone.utc).timestamp())
MAX_PAGES = 15


def log(*a):
    print(datetime.now(timezone.utc).strftime("%H:%M:%S"), *a, flush=True)


def get_json(url, tries=4):
    """FxTwitter has frequent false 404s/timeouts from datacenter IPs: retry with backoff."""
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.load(r)
        except Exception as e:
            if i == tries - 1:
                log("fetch failed:", url, e)
            else:
                time.sleep(3 * (i + 1))
    return None


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def team_items(stop_at_id):
    """Team posts+replies newest first, paging back until stop_at_id or CARDS_SINCE.
    Returns (items, complete) - complete=False if a page failed before reaching the stop."""
    items, cursor = {}, None
    for _ in range(MAX_PAGES):
        q = urllib.parse.quote(f"from:{TEAM}")
        d = get_json(f"{FX}/search?q={q}&feed=latest&count=40" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else ""))
        res = (d or {}).get("results")
        if not res:
            return items, False
        for s in res:
            if ((s.get("author") or {}).get("screen_name") or "").lower() == TEAM:
                items[s["id"]] = s
        oldest = min(res, key=lambda s: int(s["id"]))
        if int(oldest["id"]) <= stop_at_id or (oldest.get("created_timestamp") or 0) < CARDS_SINCE:
            return items, True
        c = d.get("cursor")
        cursor = c.get("bottom") if isinstance(c, dict) else c
        if not cursor:
            return items, True
    return items, False


def is_award(s):
    return "memory card unlocked" in (s.get("text") or "").lower()


QUEST_RE = re.compile(r"side quest\s*:", re.I)


def parse_quest(s):
    text = s.get("text") or ""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title = re.sub(r"[«»]", "", lines[0]).strip() if lines else ""
    prompt = next((QUEST_RE.split(l, 1)[1].strip() for l in lines if QUEST_RE.search(l)), "")
    hint = next((l.split(":", 1)[1].strip() for l in lines if l.lower().startswith("hint")), "")
    partner = (re.findall(r"@(\w+)", title) or [None])[0]
    return {"id": s["id"], "at": iso(s["created_timestamp"]), "url": s.get("url"), "title": title,
            "prompt": prompt, "hint": hint, "partner": partner,
            "rewards": [l.lstrip("▸ ").strip() for l in lines if "→" in l]}


# A build = a link to something they made (not X / the nulls site) or explicit build words.
# ("the team that built zkSNARKs" is not a build; "I finally sat down and built something" is.)
BUILD_RE = re.compile(r"https?://(?!(?:www\.)?(?:x|twitter)\.com|t\.co|nulls\.world)\S+"
                      r"|\b(?:i|i've|i ve|we|we've)\s+(?:built|made|coded)\b"
                      r"|\bbuilt (?:a|an|my|this|something)\b|\b(?:play here|is live|try it)\b", re.I)
ART_RE = re.compile(r"\b(fan ?art|drew|draw|drawing|illustrat\w*|painted|sketch|film|animation)\b", re.I)


def classify(post, quest_ids):
    if (post.get("replying_to") or {}).get("status") in quest_ids:
        return "quest"
    text = post.get("text") or ""
    if BUILD_RE.search(text):
        return "build"
    if ART_RE.search(text) or (post.get("media") or {}).get("all"):
        return "art" if ART_RE.search(text) else "post"
    return "post"


def strip_mentions(text):
    return re.sub(r"^(\s*@\w+)+\s*", "", text or "").strip()


def avatar(author):
    url = (author or {}).get("avatar_url") or ""
    return url.replace("_normal.", "_200x200.")


def new_award(s):
    rt = s.get("replying_to") or {}
    return {"id": s["id"], "at": iso(s["created_timestamp"]), "url": s.get("url"),
            "winner": rt.get("screen_name"), "for_id": rt.get("status"), "for": None}


def resolve_award(award, quest_ids):
    """The award reply points at the post that earned it; fetch that post for context.
    Leaves award["for"] = None on failure, so the next run retries it."""
    post = get_json(f"{FX}/status/{award['for_id']}") if award.get("for_id") else None
    post = (post or {}).get("status")
    if post:
        a = post.get("author") or {}
        award.update(winner=a.get("screen_name") or award["winner"], name=a.get("name"), avatar=avatar(a))
        award["for"] = {"id": post["id"], "url": post.get("url"), "at": iso(post["created_timestamp"]),
                        "text": strip_mentions(post.get("text"))[:280], "kind": classify(post, quest_ids),
                        "re": (post.get("replying_to") or {}).get("status")}
    return award


AVATARS_PER_RUN = 30  # profile lookups per run, so a GitHub run stays short; the rest come next run
AVATAR_GIVE_UP = 3    # failed runs before a handle keeps the silhouette (renamed/suspended accounts 404 forever)


def list_players(known):
    """@nullslist's « PLAYER #N REGISTERED » posts merged into `known` ({N: player} from the
    last good run). New players appear at the top, so a normal run reads one page and stops as
    soon as it reaches a player it already has. Only a first run, or a page with no overlap (a
    gap), pages further back - FxTwitter's deeper pages often 404 from GitHub's servers.
    Returns None if a needed page failed: a gap would be miscounted as skipped numbers."""
    players, cursor = dict(known), None
    for _ in range(MAX_PAGES):
        d = get_json(f"{FX}/profile/{LIST}/statuses?count=100" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else ""))
        res = (d or {}).get("results")
        if res is None:
            return None
        new = overlap = 0
        for s in res:
            m = re.search(r"PLAYER #(\d+) REGISTERED", s.get("text") or "")
            if not m:
                continue
            no = int(m.group(1))
            if no in known:
                overlap += 1
            elif no not in players:
                who = re.findall(r"@(\w+)", s.get("text") or "")
                players[no] = {"no": no, "handle": who[0] if who else None,
                               "at": iso(s["created_timestamp"]), "url": s.get("url")}
                new += 1
        c = d.get("cursor")
        cursor = c.get("bottom") if isinstance(c, dict) else c
        if overlap or not res or not new or not cursor:
            break
    return players or None


def list_summary(players):
    """Neither the highest N nor the number of posts is the player count: @nullslist only
    started announcing at #024 (Oct 29; #001-#023 got in before it existed) and skipped #099.
    So count = newest - numbers missing since announcing began (#114 newest -> 113 players)."""
    newest, first = max(players), min(players)
    skipped = [n for n in range(first, newest) if n not in players]
    return {"count": newest - len(skipped), "newest": newest, "first_announced": first, "skipped": skipped,
            "latest": players[newest]["handle"], "at": players[newest]["at"]}


def fill_avatars(players, known):
    """Give players an avatar: reuse ones already known (e.g. card winners), else look up at
    most AVATARS_PER_RUN profiles, one quick try each. A handle that fails AVATAR_GIVE_UP runs
    is left alone (the page draws a nulls silhouette), so dead accounts can't slow every run."""
    todo = []
    for p in players:
        if not p.get("avatar") and p.get("handle"):
            p["avatar"] = known.get(p["handle"].lower())
            if not p["avatar"] and p.get("avatar_misses", 0) < AVATAR_GIVE_UP:
                todo.append(p)
    for p in todo[:AVATARS_PER_RUN]:
        d = get_json(f"{FX}/profile/{p['handle']}", tries=1)
        p["avatar"] = avatar((d or {}).get("user")) or None
        if not p["avatar"]:
            p["avatar_misses"] = p.get("avatar_misses", 0) + 1
        time.sleep(0.5)  # be gentle: many lookups in a row get throttled


def solve(quests, awards):
    for q in quests:
        wins = sorted((a for a in awards if a.get("for") and a["for"].get("re") == q["id"]), key=lambda a: a["for"]["at"])
        if wins:
            w, t0 = wins[0], datetime.fromisoformat(q["at"].replace("Z", "+00:00"))
            q.update(solved_by=w["winner"], answer=w["for"]["text"][:80], solved_at=w["for"]["at"],
                     solve_secs=int((datetime.fromisoformat(w["for"]["at"].replace("Z", "+00:00")) - t0).total_seconds()))
        else:
            q.update(solved_by=None, answer=None, solved_at=None, solve_secs=None)


def collect(ledger):
    """Return the updated ledger. Never mutates `ledger`: main() compares old vs new to
    decide whether anything changed, so editing old entries in place would hide changes."""
    ledger = json.loads(json.dumps(ledger))
    awards = {a["id"]: a for a in ledger.get("awards", [])}
    quests = {q["id"]: q for q in ledger.get("quests", [])}
    items, complete = team_items(int(ledger.get("scanned_to", "0")))
    for s in items.values():
        if QUEST_RE.search(s.get("text") or "") and s["id"] not in quests:
            quests[s["id"]] = parse_quest(s)
    for s in items.values():
        if is_award(s) and s["id"] not in awards:
            awards[s["id"]] = new_award(s)
    for a in awards.values():  # new ones, plus any whose post failed to load last time
        if a.get("for") is None:
            resolve_award(a, set(quests))
    new = dict(ledger)
    new["awards"] = sorted(awards.values(), key=lambda a: int(a["id"]))
    new["quests"] = sorted(quests.values(), key=lambda q: int(q["id"]))
    solve(new["quests"], new["awards"])
    if complete and items:
        new["scanned_to"] = str(max(int(ledger.get("scanned_to", "0")), max(int(i) for i in items)))
    players = list_players({p["no"]: p for p in ledger.get("players", [])})  # known ones keep avatars/misses
    if players:
        known = {a["winner"].lower(): a["avatar"] for a in new["awards"] if a.get("winner") and a.get("avatar")}
        new["players"] = [players[n] for n in sorted(players)]
        fill_avatars(new["players"], known)
        new["list"] = list_summary(players)
    return new


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    new = collect(old)
    content = {k: v for k, v in new.items() if k != "updated"}
    if content == {k: v for k, v in old.items() if k != "updated"}:
        log("no change")
        return
    new["updated"] = iso(int(time.time()))
    OUT.write_text(json.dumps(new, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    log(f"ledger updated: {len(new['awards'])} awards, {len(new['quests'])} quests, list {(new.get('list') or {}).get('count')}")


if __name__ == "__main__":
    main()
