"""Checks for review boundaries; synthetic events do not authorize real data."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.release import fact_content_hash, load_release
from scripts.promote_release import promote_release
from scripts.stage_update import clean_fact, stage_update

RELEASE = Path(__file__).resolve().parents[1] / "data" / "release"


def first_fact() -> dict:
    return json.loads((RELEASE / "facts.jsonl").read_text().splitlines()[0])


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(x) + "\n" for x in records))


def review_event(path: Path, fact: dict) -> Path:
    payload = {
        "event_id": "SYNTHETIC-TEST-REVIEW",
        "reviewer": "Synthetic test reviewer",
        "reviewed_on": "2026-11-18",
        "confirmed_by_human": True,
        "accepted_content_sha256": {fact["fact_id"]: fact["content_sha256"]},
        "excluded_fact_ids": ["K09"],
        "suspended_fact_ids": ["K01", "K02", "K03", "K04", "K05", "K06"],
    }
    path.write_text(json.dumps(payload))
    return path


def test_staging_changed_text_resets_acceptance_and_preserves_measurements() -> None:
    original = first_fact()
    original["statement_en"] = "  " + original["statement_en"] + "\n\t"
    candidate, audit = clean_fact(original)
    assert candidate["review"]["decision"] == "PENDING"
    assert candidate["review"]["reviewed_content_sha256"] is None
    assert candidate["record_revision"] == original["record_revision"] + 1
    assert candidate["value"] == original["value"]
    assert candidate["scope"] == original["scope"]
    assert candidate["provenance"] == original["provenance"]
    assert candidate["content_sha256"] == fact_content_hash(candidate)
    assert audit["review_reset_to_pending"]


def test_staging_unchanged_text_does_not_carry_acceptance() -> None:
    original = first_fact()
    candidate, audit = clean_fact(original)
    assert candidate["record_revision"] == original["record_revision"]
    assert candidate["content_sha256"] == original["content_sha256"]
    assert candidate["review"]["decision"] == "PENDING"
    assert audit["changed_fields"] == []


def test_staging_cannot_write_into_current_release() -> None:
    with pytest.raises(ValueError, match="data/release"):
        stage_update(RELEASE / "facts.jsonl", RELEASE / "staging-candidates")


def test_clean_input_changed_outside_normalizer_gets_new_revision(tmp_path: Path) -> None:
    fact = first_fact()
    fact["statement_en"] += " Changed draft wording."
    path = tmp_path / "input.jsonl"
    write_jsonl(path, [fact])
    output = stage_update(path, tmp_path / "staged")
    candidate = json.loads((output / "facts.candidates.jsonl").read_text())
    assert candidate["record_revision"] == fact["record_revision"] + 1
    assert candidate["review"]["decision"] == "PENDING"
    assert candidate["value"] == fact["value"]
    assert not (output / "manifest.json").exists()


def test_old_review_cannot_cross_changed_hash(tmp_path: Path) -> None:
    fact = deepcopy(first_fact())
    event = review_event(tmp_path / "review.json", fact)
    fact["statement_en"] += " Additional unsupported text."
    fact["content_sha256"] = fact_content_hash(fact)
    facts_path = tmp_path / "changed.jsonl"
    write_jsonl(facts_path, [fact])
    with pytest.raises(ValueError, match="stale human acceptance"):
        promote_release(
            facts_path,
            RELEASE / "sources.jsonl",
            RELEASE / "scope.json",
            event,
            tmp_path / "new-release",
            "SYNTHETIC-TEST-RELEASE",
        )
    assert not (tmp_path / "new-release").exists()


def test_existing_output_is_never_overwritten(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    (output / "sentinel.txt").write_text("keep")
    with pytest.raises(ValueError, match="never overwritten"):
        promote_release(
            RELEASE / "facts.jsonl",
            RELEASE / "sources.jsonl",
            RELEASE / "scope.json",
            tmp_path / "nonexistent-event.json",
            output,
            "SYNTHETIC-TEST-RELEASE",
        )
    assert (output / "sentinel.txt").read_text() == "keep"


def test_retired_distance_is_refused_even_with_matching_synthetic_acceptance(
    tmp_path: Path,
) -> None:
    fact = deepcopy(first_fact())
    fact["fact_id"] = "K09"
    fact["content_sha256"] = fact_content_hash(fact)
    fact["review"]["reviewed_content_sha256"] = fact["content_sha256"]
    facts_path = tmp_path / "retired.jsonl"
    write_jsonl(facts_path, [fact])
    with pytest.raises(ValueError, match="cannot be restored"):
        promote_release(
            facts_path,
            RELEASE / "sources.jsonl",
            RELEASE / "scope.json",
            review_event(tmp_path / "review.json", fact),
            tmp_path / "blocked",
            "SYNTHETIC-TEST-RELEASE",
        )


def test_valid_reviewed_subset_is_validated_before_promotion(tmp_path: Path) -> None:
    fact = first_fact()
    path = tmp_path / "facts.jsonl"
    write_jsonl(path, [fact])
    output = promote_release(
        path,
        RELEASE / "sources.jsonl",
        RELEASE / "scope.json",
        review_event(tmp_path / "review.json", fact),
        tmp_path / "reviewed-release",
        "SYNTHETIC-TEST-RELEASE",
    )
    released = load_release(output)
    assert [f["fact_id"] for f in released.facts] == [fact["fact_id"]]
    assert released.manifest["production_ready"] is False
    assert released.manifest["local_prototype_use"] is True
    assert released.manifest["excluded_fact_ids"] == ["K09"]
    assert released.manifest["suspended_fact_ids"] == ["K01", "K02", "K03", "K04", "K05", "K06"]
    assert "review_event.audit.json" in released.manifest["files"]
