#!/usr/bin/env python3
"""Refresh the public Google Scholar statistics embedded in index.html."""

from __future__ import annotations

import datetime as dt
import html
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path


SCHOLAR_ID = "KBJ9ooAAAAAJ"
ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"


def fetch_profile() -> str:
    query = urllib.parse.urlencode(
        {
            "user": SCHOLAR_ID,
            "hl": "en",
            "view_op": "list_works",
            "sortby": "pubdate",
            "pagesize": "100",
        }
    )
    request = urllib.request.Request(
        f"https://scholar.google.com/citations?{query}",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_stats(profile: str) -> tuple[int, int, int, int]:
    values = [
        int(html.unescape(value).replace(",", ""))
        for value in re.findall(
            r'<td[^>]*class="gsc_rsb_std"[^>]*>\s*([\d,]+)\s*</td>', profile
        )
    ]
    publications = len(re.findall(r'<tr[^>]*class="gsc_a_tr"', profile))
    if len(values) < 6 or publications == 0:
        raise RuntimeError(
            "Google Scholar did not return the expected public profile markup; "
            "the existing homepage values were left unchanged."
        )
    citations, h_index, i10_index = values[0], values[2], values[4]
    return publications, citations, h_index, i10_index


def replace_value(document: str, element_id: str, value: int) -> str:
    pattern = rf'(<strong id="{re.escape(element_id)}">)\d+(</strong>)'
    updated, count = re.subn(pattern, rf"\g<1>{value}\g<2>", document, count=1)
    if count != 1:
        raise RuntimeError(f"Could not find #{element_id} in index.html")
    return updated


def update_homepage(stats: tuple[int, int, int, int]) -> None:
    document = INDEX.read_text(encoding="utf-8")
    for element_id, value in zip(
        (
            "scholar-publications",
            "scholar-citations",
            "scholar-h-index",
            "scholar-i10-index",
        ),
        stats,
    ):
        document = replace_value(document, element_id, value)

    today = dt.date.today()
    english = f"Google Scholar · Updated {today.strftime('%B %Y')}"
    chinese = f"Google Scholar · 更新于 {today.year} 年 {today.month} 月"
    note = (
        f'<p class="stats-note" id="scholar-updated" data-en="{english}" '
        f'data-zh="{chinese}">{english}</p>'
    )
    document, count = re.subn(
        r'<p class="stats-note" id="scholar-updated"[^>]*>.*?</p>',
        note,
        document,
        count=1,
    )
    if count != 1:
        raise RuntimeError("Could not find the Scholar update timestamp in index.html")
    INDEX.write_text(document, encoding="utf-8", newline="\n")


def main() -> int:
    stats = parse_stats(fetch_profile())
    update_homepage(stats)
    print(
        "Updated Scholar statistics: "
        f"publications={stats[0]}, citations={stats[1]}, "
        f"h-index={stats[2]}, i10-index={stats[3]}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Scholar update skipped: {error}", file=sys.stderr)
        raise SystemExit(1)
