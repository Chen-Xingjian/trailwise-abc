"""Compare public source material with audit fingerprints. The fact release stays read-only."""

import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import os
import re
import time
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

import httpx

from app.config import ROOT
from app.release import canonical_hash, load_release


class ArticleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "header"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "header"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def fingerprint(rule, body):
    kind = rule["kind"]
    if kind == "file":
        if not body or b"<html" in body[:500].lower():
            raise ValueError("expected data file")
        return hashlib.sha256(body).hexdigest()
    if kind == "wiki":
        (page,) = json.loads(body)["query"]["pages"].values()
        return str(page["revisions"][0]["revid"])
    if kind == "osm":
        rows = json.loads(body)["elements"]
        if not rows:
            raise ValueError("OSM object missing")
        return canonical_hash(sorted(rows, key=lambda x: (x["type"], x["id"])))
    if kind == "era5":
        rows = json.loads(body)
        if len(rows) != 3 or not all(r.get("daily", {}).get("time") for r in rows):
            raise ValueError("missing archived climate data")
        return canonical_hash(
            [{k: v for k, v in r.items() if k != "generationtime_ms"} for r in rows]
        )
    html = body.decode("utf-8", errors="replace")
    if kind == "time_labels":
        panel = html.split("dclk-panel--abc", 1)[-1].split("dclk-panel--ebc", 1)[0]
        labels = re.findall(
            r'aria-label="(Day (\d+): \d+h \d+m door to door, \d+h \d+m moving)"', panel
        )
        if [n for _, n in labels] != list("123456") or "dclk-panel--abc" not in html:
            raise ValueError("six audited labels unavailable")
        return canonical_hash(labels)
    parser = ArticleText()
    parser.feed(html)
    text = " ".join(" ".join(parser.parts).split())
    if rule["marker"].casefold() not in text.casefold():
        raise ValueError("reviewed page marker missing")
    return hashlib.sha256(text.encode()).hexdigest()


def targets_for(release, rules):
    facts = {f["fact_id"]: f for f in release.facts}
    result = []
    for rule in rules:
        sources = set(rule.get("sources", []))
        affected = {
            i for i, f in facts.items() if any(p["source_id"] in sources for p in f["provenance"])
        }
        affected.update(set(rule.get("facts", [])) & facts.keys())
        if not affected:
            continue
        while True:
            extra = {
                i
                for i, f in facts.items()
                if affected.intersection(f["dependencies"]["required_fact_ids"])
            }
            if extra <= affected:
                break
            affected |= extra
        result.append({**rule, "facts": sorted(affected)})
    return result


def compare(rule, prior, fingerprint_now, checked, error=None):
    baseline = prior.get("baseline") or rule.get("audit_fingerprint")
    if error:
        return {
            **prior,
            "id": rule["id"],
            "url": rule["url"],
            "facts": rule["facts"],
            "baseline": baseline,
            "last_attempt": checked,
            "availability": "unavailable",
            "error": error,
            "comparison": prior.get("comparison", "unchecked"),
        }
    if baseline is None:
        baseline = fingerprint_now
    return {
        "id": rule["id"],
        "url": rule["url"],
        "facts": rule["facts"],
        "baseline": baseline,
        "baseline_kind": prior.get("baseline_kind")
        or ("audit" if rule.get("audit_fingerprint") else "first successful lookup"),
        "observed": fingerprint_now,
        "last_attempt": checked,
        "last_success": checked,
        "availability": "available",
        "comparison": "changed"
        if baseline != fingerprint_now
        else (
            "matches reviewed revision"
            if prior.get("baseline_kind") == "human-reviewed monitoring revision"
            else (
                "matches audit" if rule.get("audit_fingerprint") else "matches monitoring baseline"
            )
        ),
    }


def report_dir(release_dir, root):
    digest = hashlib.sha256((release_dir / "manifest.json").read_bytes()).hexdigest()
    return root / "source-watch" / digest


def scan(release_dir, root, *, force=False, client=None, now=None):
    release = load_release(release_dir)
    directory = report_dir(release_dir, root)
    directory.mkdir(parents=True, exist_ok=True)
    checked = now or datetime.now(UTC)
    latest = directory / "latest.json"
    config = json.loads((ROOT / "config/abc_source_watch.json").read_text())
    rules = targets_for(release, config)
    with (directory / "scan.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = json.loads(latest.read_text()) if latest.exists() else {}
        old = {r["id"]: r for r in previous.get("targets", [])}
        due = []
        for rule in rules:
            prior = old.get(rule["id"], {})
            days = 1 if prior.get("availability") == "unavailable" else rule.get("interval_days", 7)
            if (
                force
                or not prior
                or checked >= datetime.fromisoformat(prior["last_attempt"]) + timedelta(days=days)
            ):
                due.append(rule)
        if not due and previous:
            return previous

        def fetch(rule):
            prior = old.get(rule["id"], {})
            try:
                response = client.get(rule["url"])
                response.raise_for_status()
                value = fingerprint(rule, response.content)
                return compare(rule, prior, value, checked.isoformat())
            except (
                httpx.HTTPError,
                ValueError,
                KeyError,
                TypeError,
                IndexError,
                AttributeError,
            ) as exc:
                return compare(rule, prior, None, checked.isoformat(), str(exc))

        own_client = client is None
        if own_client:
            client = httpx.Client(
                timeout=22,
                follow_redirects=True,
                headers={"User-Agent": "Trailwise-ABC-Research/1.0 (source review)"},
            )
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                updated = {r["id"]: r for r in pool.map(fetch, due)}
        finally:
            if own_client:
                client.close()
        rows = [{**(updated.get(r["id"]) or old[r["id"]]), "facts": r["facts"]} for r in rules]
        mapped = {i for row in rows for i in row["facts"]}
        result = {
            "review_history": previous.get("review_history", []),
            "release": release.manifest["release_id"],
            "checked_at": checked.isoformat(),
            "targets": rows,
            "manual_fact_ids": sorted(
                f["fact_id"] for f in release.facts if f["fact_id"] not in mapped
            ),
            "review_fact_ids": sorted(
                {i for r in rows if r["comparison"] == "changed" for i in r["facts"]}
            ),
            "unavailable_fact_ids": sorted(
                {i for r in rows if r["availability"] == "unavailable" for i in r["facts"]}
            ),
        }
        write_report(directory, result, checked)
        return result


def write_report(directory, result, checked):
    data = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    history = directory / checked.strftime("%Y%m%dT%H%M%S%fZ.json")
    with history.open("x") as file:
        file.write(data)
    temp = directory / "latest.tmp"
    temp.write_text(data)
    os.replace(temp, directory / "latest.json")


def acknowledge(directory, target, observed, reason):
    """Mark a specific changed revision as reviewed without editing a frozen fact."""
    with (directory / "scan.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = json.loads((directory / "latest.json").read_text())
        row = next((r for r in result["targets"] if r["id"] == target), None)
        if (
            not row
            or row.get("observed") != observed
            or row["availability"] != "available"
            or row["comparison"] != "changed"
            or not reason.strip()
        ):
            raise ValueError(
                "Review requires a changed, available target, matching observed fingerprint and a reason."
            )
        now = datetime.now(UTC)
        decision = dict(
            at_utc=now.isoformat(),
            target=target,
            previous=row["baseline"],
            reviewed=observed,
            affected_fact_ids=row["facts"],
            reason=reason,
        )
        result.setdefault("review_history", []).append(decision)
        row.update(
            baseline=observed,
            baseline_kind="human-reviewed monitoring revision",
            comparison="matches reviewed revision",
        )
        result["review_fact_ids"] = sorted(
            {i for r in result["targets"] if r["comparison"] == "changed" for i in r["facts"]}
        )
        write_report(directory, result, now)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument(
        "--watch", action="store_true", help="Check due sources hourly while running"
    )
    parser.add_argument("--force", action="store_true", help="Fetch all sources once")
    parser.add_argument(
        "--affirm-unaffected",
        nargs=3,
        metavar=("TARGET", "OBSERVED", "REASON"),
        help="Record an explicit human review of an exact source revision",
    )
    args = parser.parse_args()
    if args.affirm_unaffected:
        acknowledge(report_dir(args.release, args.runtime), *args.affirm_unaffected)
        return
    while True:
        report = scan(args.release, args.runtime, force=args.force)
        print(
            f"Source watch: {len(report['targets'])} targets; {len(report['review_fact_ids'])} facts flagged; "
            f"{report_dir(args.release, args.runtime) / 'latest.json'}",
            flush=True,
        )
        if not args.watch:
            break
        time.sleep(3600)


if __name__ == "__main__":
    main()
