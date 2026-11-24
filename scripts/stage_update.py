"""Prepare unapproved fact candidates without changing measurement or entity fields."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import unicodedata
from copy import deepcopy
from pathlib import Path

from app.release import fact_content_hash, load_release

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROTECTED_RELEASE = PROJECT_ROOT / "data" / "release"
TEXT_FIELDS = ("statement_en", "qualification_en")


def read_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict):
            raise ValueError(f"Line {number} must contain an object")
        records.append(record)
    return records


def check_new_output(output: Path) -> Path:
    resolved = output.expanduser().resolve()
    protected = PROTECTED_RELEASE.resolve()
    if resolved == protected or protected in resolved.parents:
        raise ValueError("Staging cannot write inside data/release")
    if resolved.exists():
        raise ValueError("Output already exists; use a new staging directory")
    return resolved


def clean_fact(record: dict, base_record: dict | None = None) -> tuple[dict, dict]:
    """Normalize narrative text only; all outputs need a new human decision."""
    fact = deepcopy(record)
    fact_id = fact.get("fact_id")
    if not isinstance(fact_id, str) or not fact_id.strip():
        raise ValueError("A stable fact_id is required")
    revision = fact.get("record_revision", 1)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError(f"Invalid record_revision for {fact_id}")
    governance = fact.setdefault("governance", {})
    if not isinstance(governance, dict):
        raise ValueError(f"governance must be an object for {fact_id}")
    changed: list[str] = []
    for field in TEXT_FIELDS:
        value = fact.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{field} must be text for {fact_id}")
        if isinstance(value, str):
            cleaned = " ".join(unicodedata.normalize("NFKC", value).split())
            if cleaned != value:
                fact[field] = cleaned
                changed.append(field)
    baseline_changed = None
    if base_record is not None:
        if base_record["fact_id"] != fact_id:
            raise ValueError("Baseline fact ID must match candidate")
        baseline_revision = base_record["record_revision"]
        comparable = deepcopy(fact)
        comparable["record_revision"] = baseline_revision
        baseline_changed = fact_content_hash(comparable) != fact_content_hash(base_record)
        fact["record_revision"] = baseline_revision + 1 if baseline_changed else baseline_revision
    else:
        fact["record_revision"] = revision + 1 if changed else revision
    governance["release_review_status"] = "PENDING_HUMAN_ACCEPTANCE"
    governance["production_eligible"] = False
    fact["review"] = {
        "decision": "PENDING",
        "reviewer": None,
        "reviewed_on": None,
        "checks_confirmed": False,
        "reviewed_content_sha256": None,
        "comment": None,
    }
    fact["content_sha256"] = fact_content_hash(fact)
    audit = {
        "fact_id": fact_id,
        "previous_content_sha256": record.get("content_sha256"),
        "candidate_content_sha256": fact["content_sha256"],
        "previous_record_revision": revision,
        "candidate_record_revision": fact["record_revision"],
        "changed_fields": changed,
        "baseline_record_revision": base_record["record_revision"] if base_record else None,
        "changed_from_reviewed_baseline": baseline_changed,
        "protected_fields_unchanged": ["value", "scope", "provenance", "fact_id"],
        "review_reset_to_pending": True,
        "retrieval_use": False,
    }
    return fact, audit


def stage_update(
    facts_path: Path, output: Path, base_release: Path = PROTECTED_RELEASE
) -> Path:
    output = check_new_output(output)
    base_release = base_release.expanduser().resolve()
    if base_release in output.parents:
        raise ValueError("Staging cannot write inside its baseline release")
    records = read_jsonl(facts_path)
    if not records:
        raise ValueError("No candidate records supplied")
    base_facts = {fact["fact_id"]: fact for fact in load_release(base_release).facts}
    prepared = [clean_fact(record, base_facts.get(record.get("fact_id"))) for record in records]
    ids = [fact["fact_id"] for fact, _ in prepared]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate fact_id in staging input")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        text = "".join(
            json.dumps(fact, ensure_ascii=False, separators=(",", ":")) + "\n"
            for fact, _ in prepared
        )
        (temporary / "facts.candidates.jsonl").write_text(text, encoding="utf-8")
        log = {
            "stage": "UNAPPROVED_CANDIDATES",
            "production_ready": False,
            "retrieval_use": False,
            "baseline_release": str(base_release.resolve()),
            "rule": "Review original evidence, rights, scope and the exact new hash before acceptance.",
            "records": [audit for _, audit in prepared],
        }
        (temporary / "cleaning_log.audit.json").write_text(
            json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if output.exists():
            raise ValueError("Output was created during staging; refusing to overwrite")
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-release", type=Path, default=PROTECTED_RELEASE)
    args = parser.parse_args()
    try:
        output = stage_update(args.facts, args.output, args.base_release)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"Staging failed: {exc}\n")
    print(f"Unapproved candidates written to {output}")


if __name__ == "__main__":
    main()
