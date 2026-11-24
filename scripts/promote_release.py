"""Create a new local-prototype release from explicitly reviewed payloads."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import date
from pathlib import Path

from app.release import (
    canonical_hash,
    fact_content_hash,
    load_release,
    source_content_hash,
)

EXCLUDED_FACT_IDS = frozenset({"K09"})
SUSPENDED_FACT_IDS = frozenset({"K01", "K02", "K03", "K04", "K05", "K06"})


def read_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if line.strip():
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"Line {number} must contain an object")
            records.append(record)
    return records


def _id_list(event: dict, field: str) -> set[str]:
    value = event.get(field, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of stable fact IDs")
    return set(value)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in records),
        encoding="utf-8",
    )


def _review_event(path: Path) -> dict:
    event = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(event, dict):
        raise ValueError("Review event must be an object")
    if event.get("confirmed_by_human") is not True:
        raise ValueError("An explicit human-confirmed review event is required")
    if not isinstance(event.get("reviewer"), str) or not event["reviewer"].strip():
        raise ValueError("Review event requires a reviewer")
    if not isinstance(event.get("event_id"), str) or not event["event_id"].strip():
        raise ValueError("Review event requires a stable event_id")
    date.fromisoformat(event.get("reviewed_on", ""))
    if not isinstance(event.get("accepted_content_sha256"), dict):
        raise ValueError("Review event requires accepted_content_sha256")
    return event


def promote_release(
    facts_path: Path,
    sources_path: Path,
    scope_path: Path,
    review_event_path: Path,
    output: Path,
    release_id: str,
) -> Path:
    output = output.expanduser().resolve()
    if output.exists():
        raise ValueError("Output already exists; releases are never overwritten")
    if not release_id.strip():
        raise ValueError("A release ID is required")
    event = _review_event(review_event_path)
    excluded = set(EXCLUDED_FACT_IDS) | _id_list(event, "excluded_fact_ids")
    suspended = (
        set(SUSPENDED_FACT_IDS)
        | _id_list(event, "suspended_fact_ids")
        | _id_list(event, "suspended_distance_fact_ids")
    )
    denied = excluded | suspended
    facts = read_jsonl(facts_path)
    sources_input = read_jsonl(sources_path)
    scope = json.loads(scope_path.read_text(encoding="utf-8"))
    if not isinstance(scope, dict) or not facts:
        raise ValueError("A scope object and at least one reviewed fact are required")
    fact_ids = [fact.get("fact_id") for fact in facts]
    if any(not isinstance(fid, str) or not fid for fid in fact_ids):
        raise ValueError("Every fact requires a stable fact_id")
    if len(fact_ids) != len(set(fact_ids)):
        raise ValueError("Duplicate fact IDs")
    if denied.intersection(fact_ids):
        raise ValueError("Excluded or suspended distance facts cannot be restored by this CLI")
    for fact in facts:
        fid = fact["fact_id"]
        digest = fact_content_hash(fact)
        review = fact.get("review", {})
        if (
            review.get("decision") != "ACCEPT"
            or review.get("checks_confirmed") is not True
            or not isinstance(review.get("reviewer"), str)
            or not review["reviewer"].strip()
            or review.get("reviewed_content_sha256") != digest
            or fact.get("content_sha256") != digest
            or event["accepted_content_sha256"].get(fid) != digest
            or fact.get("governance", {}).get("release_review_status") != "HUMAN_ACCEPTED"
        ):
            raise ValueError(f"Missing or stale human acceptance for {fid}")
        if fact.get("governance", {}).get("production_eligible") is not False:
            raise ValueError("This CLI creates local-prototype releases, not production approvals")
    source_map = {source.get("source_id"): source for source in sources_input}
    if len(source_map) != len(sources_input) or None in source_map:
        raise ValueError("Missing or duplicate source IDs")
    used_ids = {p["source_id"] for fact in facts for p in fact.get("provenance", [])}
    if not used_ids or not used_ids <= source_map.keys():
        raise ValueError("Every referenced source must be supplied")
    sources = [source_map[sid] for sid in sorted(used_ids)]
    for source in sources:
        digest = source_content_hash(source)
        review = source.get("rights_review", {})
        if (
            source.get("source_record_sha256") != digest
            or review.get("decision") != "ACCEPT"
            or review.get("checks_confirmed") is not True
            or not isinstance(review.get("reviewer"), str)
            or not review["reviewer"].strip()
            or review.get("reviewed_source_record_sha256") != digest
        ):
            raise ValueError(f"Missing or stale source rights acceptance for {source['source_id']}")
    for fact in facts:
        for provenance in fact.get("provenance", []):
            source = source_map[provenance["source_id"]]
            if (
                provenance.get("source_record_sha256") != source["source_record_sha256"]
                or provenance.get("source_record_revision") != source["record_revision"]
            ):
                raise ValueError(f"Stale source dependency for {fact['fact_id']}")
    scope = dict(scope)
    scope["release_id"] = release_id
    scope["accepted_fact_ids"] = fact_ids
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        _write_jsonl(temporary / "facts.jsonl", facts)
        _write_jsonl(temporary / "sources.jsonl", sources)
        (temporary / "scope.json").write_text(
            json.dumps(scope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        attribution = "\n\n".join(str(source.get("attribution", "")) for source in sources)
        (temporary / "ATTRIBUTION.txt").write_text(attribution + "\n", encoding="utf-8")
        (temporary / "review_event.audit.json").write_text(
            json.dumps(event, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        manifest = {
            "schema_version": "1.0.0",
            "release_id": release_id,
            "created_on": event["reviewed_on"],
            "stage": "LOCAL_PROTOTYPE_REVIEWED_INCREMENT",
            "local_prototype_use": True,
            "production_ready": False,
            "fact_file": "facts.jsonl",
            "source_file": "sources.jsonl",
            "scope_file": "scope.json",
            "attribution_file": "ATTRIBUTION.txt",
            "fact_count": len(facts),
            "source_count": len(sources),
            "allowed_fact_ids": fact_ids,
            "accepted_fact_hashes": {fact["fact_id"]: fact["content_sha256"] for fact in facts},
            "allowed_source_ids": sorted(used_ids),
            "source_record_hashes": {
                source["source_id"]: source["source_record_sha256"] for source in sources
            },
            "licence_ids": sorted({source["licence_id"] for source in sources}),
            "manual_review_event": {
                "event_id": event["event_id"],
                "reviewer": event["reviewer"],
                "reviewed_on": event["reviewed_on"],
                "confirmed_by_human": True,
                "event_sha256": canonical_hash(event),
                "audit_file": "review_event.audit.json",
            },
            "excluded_fact_ids": sorted(excluded),
            "suspended_fact_ids": sorted(suspended - excluded),
            "files": {},
        }
        for name in [
            "facts.jsonl", "sources.jsonl", "scope.json", "ATTRIBUTION.txt", "review_event.audit.json"
        ]:
            payload = (temporary / name).read_bytes()
            manifest["files"][name] = {
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        # Validate the complete staged release before it becomes visible as output.
        load_release(temporary)
        if output.exists():
            raise ValueError("Output was created during validation; refusing to overwrite")
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--review-event", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    args = parser.parse_args()
    try:
        output = promote_release(
            args.facts, args.sources, args.scope, args.review_event, args.output, args.release_id
        )
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(2, f"Release rejected: {exc}\n")
    print(f"Validated local-prototype release created at {output}; not activated automatically")


if __name__ == "__main__":
    main()
