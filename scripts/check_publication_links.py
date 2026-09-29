#!/usr/bin/env python3
"""Check public links in the Selected Publications section of the homepage."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import html.parser
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_HTML = ROOT / "index.html"
DEFAULT_REPORT = ROOT / "link-check-report.md"
SKIPPED_HOSTS = {"scholar.google.com", "scholar.google.com.hk"}
SOFT_NETWORK_ERROR_HOSTS = {"huggingface.co"}
ACCEPTED_HTTP_ERRORS = {401, 403, 429}


class PublicationLinkParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_publications = False
        self.section_depth = 0
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "section" and attributes.get("id") == "publications":
            self.in_publications = True
            self.section_depth = 1
            return
        if not self.in_publications:
            return
        if tag == "section":
            self.section_depth += 1
        if tag == "a" and attributes.get("href"):
            self.links.append(attributes["href"] or "")

    def handle_endtag(self, tag: str) -> None:
        if self.in_publications and tag == "section":
            self.section_depth -= 1
            if self.section_depth == 0:
                self.in_publications = False


def collect_links(document: pathlib.Path) -> list[str]:
    parser = PublicationLinkParser()
    parser.feed(document.read_text(encoding="utf-8"))
    return sorted(set(parser.links))


def check_local_link(url: str, document: pathlib.Path) -> tuple[str, str, bool]:
    target = urllib.parse.urlsplit(url).path
    if not target or target == "/":
        path = document
    else:
        path = ROOT / target.lstrip("/")
    exists = path.exists()
    return url, "local file found" if exists else f"missing local file: {path}", exists


def check_remote_link(url: str) -> tuple[str, str, bool]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.hostname in SKIPPED_HOSTS:
        return url, "skipped (Google Scholar rate limiting)", True

    request = urllib.request.Request(
        urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")),
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
        },
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                status = response.getcode()
                return url, f"HTTP {status}", 200 <= status < 400
        except urllib.error.HTTPError as error:
            if error.code in ACCEPTED_HTTP_ERRORS:
                return url, f"HTTP {error.code} (reachable but access-limited)", True
            return url, f"HTTP {error.code}", False
        except Exception as error:  # Retry transient transport and DNS failures.
            last_error = error
            if attempt < 2:
                time.sleep(2**attempt)

    detail = f"{type(last_error).__name__}: {last_error}"
    if parsed.hostname in SOFT_NETWORK_ERROR_HOSTS:
        return url, f"warning after retries: {detail}", True
    return url, detail, False


def check_link(url: str, document: pathlib.Path) -> tuple[str, str, bool]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme in {"http", "https"}:
        return check_remote_link(url)
    if parsed.scheme in {"mailto", "tel", "data", "javascript"} or url.startswith("#"):
        return url, "skipped", True
    return check_local_link(url, document)


def write_report(results: list[tuple[str, str, bool]], report: pathlib.Path) -> None:
    failed = [result for result in results if not result[2]]
    lines = [
        "# Publication link check",
        "",
        f"Checked: {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"Result: **{'FAILED' if failed else 'PASSED'}**",
        "",
        "| Status | URL | Response |",
        "|---|---|---|",
    ]
    for url, detail, ok in results:
        safe_url = url.replace("|", "%7C")
        safe_detail = detail.replace("|", "\\|")
        lines.append(f"| {'OK' if ok else 'FAIL'} | {safe_url} | {safe_detail} |")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", type=pathlib.Path, default=DEFAULT_HTML)
    parser.add_argument("--report", type=pathlib.Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    links = collect_links(args.html)
    if not links:
        raise RuntimeError("No links were found in #publications")

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(lambda url: check_link(url, args.html), links))
    results.sort(key=lambda result: result[0])
    write_report(results, args.report)

    for url, detail, ok in results:
        print(f"{'OK' if ok else 'FAIL'} {detail}: {url}")
    failures = [result for result in results if not result[2]]
    print(f"Checked {len(results)} unique publication links; {len(failures)} failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
