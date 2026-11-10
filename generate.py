#!/usr/bin/env python3
"""Generate neofetch-style profile cards (dark_mode.svg / light_mode.svg).

Static info lives in CONFIG below. GitHub stats are fetched live when a token
is available (GITHUB_TOKEN or ACCESS_TOKEN env var); otherwise the last values
saved in stats_cache.json are reused.
"""
import datetime as dt
import json
import os
import time
import urllib.request
from html import escape
from pathlib import Path

ROOT = Path(__file__).parent
USER = "jota-atn"
LOC_EXCLUDE = {"StructComparisons"}  # repos with generated/data files
BIRTHDAY = None  # e.g. dt.date(2005, 1, 1) -> enables the Uptime line

CONFIG = [
    ("OS", "Arch Linux, Android"),
    ("Uptime", "{uptime}"),
    ("Host", "UFCG - Campina Grande, PB"),
    ("Kernel", "Computer Science Student"),
    ("IDE", "Neovim, VS Code"),
    None,
    ("Languages.Programming", "Python, Java, C, C++, TypeScript"),
    ("Languages.Computer", "HTML, CSS, Bash, SQL, Lua"),
    ("Languages.Real", "Portuguese, English"),
    None,
    ("Hobbies.Software", "Ricing Hyprland, Neovim configs"),
    ("Hobbies.Other", "Games, Music"),
    None,
    "Contact",
    ("Email", "jamqueiroz2005@gmail.com"),
    ("LinkedIn", "joão-antonio-b10289277"),
    ("GitHub", USER),
    None,
    "GitHub Stats",
    "{stats}",
]

WIDTH = 64          # characters in the info column
FONT = 16           # px
LINE = 20           # px line height
CHAR = 9.65         # approx monospace advance at 16px
PAD = 15

THEMES = {
    "dark": dict(bg="#161b22", border="#30363d", text="#c9d1d9", key="#ffa657",
                 value="#a5d6ff", dots="#616e7f", add="#3fb950", dele="#f85149"),
    "light": dict(bg="#f6f8fa", border="#d0d7de", text="#24292f", key="#953800",
                  value="#0a3069", dots="#c2cfde", add="#1a7f37", dele="#cf222e"),
}


# ---------------------------------------------------------------- stats
def gh(url, token, data=None):
    req = urllib.request.Request(
        url, data=json.dumps(data).encode() if data else None,
        headers={"Authorization": f"bearer {token}", "User-Agent": "profile-readme"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, json.loads(r.read() or b"null")


def graphql(token, query, **variables):
    _, res = gh("https://api.github.com/graphql", token, {"query": query, "variables": variables})
    if res.get("errors"):
        raise RuntimeError(res["errors"])
    return res["data"]


def fetch_stats(token):
    d = graphql(token, """
      query($login: String!) {
        user(login: $login) {
          createdAt
          followers { totalCount }
          repositoriesContributedTo(contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY]) { totalCount }
          repositories(ownerAffiliations: OWNER, first: 100) {
            totalCount
            nodes { nameWithOwner stargazerCount }
          }
        }
      }""", login=USER)["user"]

    repos = d["repositories"]["nodes"]
    stats = {
        "repos": d["repositories"]["totalCount"],
        "contributed": d["repositoriesContributedTo"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in repos),
        "followers": d["followers"]["totalCount"],
    }

    # commits: sum contribution years
    start = int(d["createdAt"][:4])
    commits = 0
    for year in range(start, dt.date.today().year + 1):
        c = graphql(token, """
          query($login: String!, $from: DateTime!, $to: DateTime!) {
            user(login: $login) { contributionsCollection(from: $from, to: $to) {
              totalCommitContributions restrictedContributionsCount } }
          }""", login=USER, **{"from": f"{year}-01-01T00:00:00Z", "to": f"{year}-12-31T23:59:59Z"})
        cc = c["user"]["contributionsCollection"]
        commits += cc["totalCommitContributions"]
    stats["commits"] = commits

    # lines of code: additions/deletions authored by USER in owned repos
    add = dele = 0
    for r in repos:
        if r["nameWithOwner"].split("/")[1] in LOC_EXCLUDE:
            continue
        url = f"https://api.github.com/repos/{r['nameWithOwner']}/stats/contributors"
        for _ in range(6):
            status, body = gh(url, token)
            if status == 200:
                break
            time.sleep(3)  # 202: GitHub is still computing
        else:
            continue
        for contributor in body or []:
            if (contributor.get("author") or {}).get("login", "").lower() == USER.lower():
                add += sum(w["a"] for w in contributor["weeks"])
                dele += sum(w["d"] for w in contributor["weeks"])
    stats["loc_add"], stats["loc_del"] = add, dele
    return stats


def load_stats():
    cache = ROOT / "stats_cache.json"
    token = os.environ.get("ACCESS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    old = json.loads(cache.read_text()) if cache.exists() else {}
    if token:
        try:
            new = fetch_stats(token)
            # keep previous LOC if the stats endpoint was still warming up
            if new["loc_add"] == 0 and old.get("loc_add"):  # noqa
                new["loc_add"], new["loc_del"] = old["loc_add"], old["loc_del"]
            cache.write_text(json.dumps(new, indent=2) + "\n")
            return new
        except Exception as e:  # noqa: BLE001
            print("stats fetch failed, using cache:", e)
    return old or dict(repos=0, contributed=0, stars=0, followers=0, commits=0, loc_add=0, loc_del=0)


def uptime():
    if not BIRTHDAY:
        return None
    today = dt.date.today()
    y = today.year - BIRTHDAY.year
    m = today.month - BIRTHDAY.month
    d = today.day - BIRTHDAY.day
    if d < 0:
        m -= 1
        prev = (today.replace(day=1) - dt.timedelta(days=1))
        d += prev.day
    if m < 0:
        y -= 1
        m += 12
    s = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"  # noqa: E731
    return f"{s(y, 'year')}, {s(m, 'month')}, {s(d, 'day')}"


# ---------------------------------------------------------------- svg
def seg(text, cls):
    return f'<tspan class="{cls}">{escape(text)}</tspan>'


def kv(key, value, width=WIDTH):
    """'. Key: ....... value' padded to `width` chars."""
    head = f". {key}:"
    dots = width - len(head) - len(value) - 2
    return [("", ". "), ("key", key), ("", ":"), ("dots", " " + "." * max(dots, 1) + " "), ("value", value)]


def header(title, width=WIDTH):
    left = f"- {title} "
    return [("", left + "—" * (width - len(left) - 3) + "-—-")]


def kv_pair(k1, v1, k2, v2, w1):
    """Two key/values on one line, the first padded to w1 chars."""
    a = kv(k1, v1, w1)
    b = kv(k2, v2, WIDTH - w1 - 1)[1:]
    return a + [("", " | ")] + b


def build_lines(stats):
    up = uptime()
    title = "jota@atn "
    lines = [[("", title + "—" * (WIDTH - len(title) - 3) + "-—-")]]
    for item in CONFIG:
        if item is None:
            lines.append([("", "")])
        elif item == "{stats}":
            s = stats
            lines.append(kv_pair("Repos", f"{s['repos']} {{Contributed: {s['contributed']}}}",
                                 "Stars", str(s["stars"]), 36))
            lines.append(kv_pair("Commits", f"{s['commits']:,}", "Followers", str(s["followers"]), 36))
            loc = s["loc_add"] - s["loc_del"]
            add, dele = f"{s['loc_add']:,}++", f"{s['loc_del']:,}--"
            tail = f"{loc:,} ( {add}, {dele} )"
            base = kv("Lines of Code on GitHub", tail)[:-1]
            lines.append(base + [("value", f"{loc:,}"), ("", " ( "), ("add", add), ("", ", "),
                                 ("del", dele), ("", " )")])
        elif isinstance(item, str):
            lines.append(header(item))
        else:
            key, value = item
            if value == "{uptime}":
                if not up:
                    continue
                value = up
            lines.append(kv(key, value))
    return lines


def render(theme, stats):
    t = THEMES[theme]
    art = (ROOT / "ascii.txt").read_text().rstrip("\n").split("\n")
    info = build_lines(stats)
    art_w = max(map(len, art))
    info_x = PAD + (art_w + 3) * CHAR
    rows = max(len(art), len(info))
    width = int(info_x + WIDTH * CHAR + PAD)
    height = PAD * 2 + rows * LINE

    art_top = PAD + LINE + (rows - len(art)) * LINE // 2
    info_top = PAD + LINE + (rows - len(info)) * LINE // 2

    out = [f'<?xml version="1.0" encoding="UTF-8"?>',
           f'<svg xmlns="http://www.w3.org/2000/svg" font-family="ConsolasFallback,Consolas,\'JetBrains Mono\',monospace" '
           f'width="{width}px" height="{height}px" font-size="{FONT}px" xml:space="preserve">',
           "<style>",
           f".key{{fill:{t['key']}}} .value{{fill:{t['value']}}} .dots{{fill:{t['dots']}}} "
           f".add{{fill:{t['add']}}} .del{{fill:{t['dele']}}} text,tspan{{white-space:pre}}",
           "</style>",
           f'<rect width="{width}px" height="{height}px" fill="{t["bg"]}" rx="15"/>',
           f'<text x="{PAD}" y="{art_top}" fill="{t["text"]}" class="ascii">']
    for i, line in enumerate(art):
        out.append(f'<tspan x="{PAD}" y="{art_top + i * LINE}">{escape(line)}</tspan>')
    out.append("</text>")
    out.append(f'<text x="{info_x:.0f}" y="{info_top}" fill="{t["text"]}">')
    for i, parts in enumerate(info):
        body = "".join(seg(txt, cls) if cls else escape(txt) for cls, txt in parts)
        out.append(f'<tspan x="{info_x:.0f}" y="{info_top + i * LINE}">{body}</tspan>')
    out.append("</text>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    stats = load_stats()
    for theme in THEMES:
        (ROOT / f"{theme}_mode.svg").write_text(render(theme, stats))
    print("generated", stats)
