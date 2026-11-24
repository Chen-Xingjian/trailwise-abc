"""Export an explicitly selected, human-accepted review subset without editing its source.

This bootstrap export creates the first local prototype dataset. Future additions must
first receive their own source and fact review, then use a new release identifier.
No recursive source discovery, fetching, embedding or model execution is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


DEFAULT_FACT_IDS = ("K07", "K08", "W01", "W02", "W03", "W04")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def fact_hash(fact: dict) -> str:
    core = {key: value for key, value in fact.items() if key not in {"content_sha256", "review"}}
    core["governance"] = {
        key: value for key, value in fact["governance"].items()
        if key not in {"release_review_status", "production_eligible"}
    }
    return canonical_hash(core)


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def select_original_lines(path: Path, key: str, identifiers: set[str]) -> bytes:
    return b"".join(
        line for line in path.read_bytes().splitlines(keepends=True)
        if json.loads(line)[key] in identifiers
    )


def export_subset(review_dir: Path, destination: Path, release_id: str, selected_ids: list[str]) -> dict:
    if destination.resolve().is_relative_to(review_dir.resolve()):
        raise ValueError("Export destination must not be inside the frozen review snapshot.")
    if tuple(selected_ids) != DEFAULT_FACT_IDS:
        raise ValueError("This bootstrap exporter requires its reviewed six-fact scope; expanded releases need a reviewed configuration.")
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("Selected fact IDs must be unique.")
    manifest = json.loads((review_dir / "release_manifest.json").read_text())
    if not manifest.get("frozen"):
        raise ValueError("The source review must be a frozen snapshot.")
    for entry in manifest["files"]:
        if file_hash(review_dir / entry["path"]) != entry["sha256"]:
            raise ValueError(f"Frozen source checksum mismatch: {entry['path']}")
    original_snapshot = {
        str(path.relative_to(review_dir)): file_hash(path)
        for path in review_dir.rglob("*") if path.is_file()
    }
    facts_by_id = {row["fact_id"]: row for row in load_rows(review_dir / "facts.draft.jsonl")}
    sources_by_id = {row["source_id"]: row for row in load_rows(review_dir / "sources.draft.jsonl")}
    uses = {row["fact_id"]: row for row in load_rows(review_dir / "current_use_registry.audit.jsonl")}
    selected: list[dict] = []
    needed_sources: set[str] = set()
    for identifier in selected_ids:
        if identifier not in facts_by_id:
            raise ValueError(f"Fact is absent from current candidates: {identifier}")
        fact = facts_by_id[identifier]
        use = uses.get(identifier, {})
        review = fact["review"]
        if use.get("current_use") != "REVIEW_CANDIDATE" or not use.get("current_candidate_accepted"):
            raise ValueError(f"Fact is inactive or has no accepted current use: {identifier}")
        if review["decision"] != "ACCEPT" or not review["reviewer"] or not review["reviewed_on"] or not review["checks_confirmed"]:
            raise ValueError(f"Incomplete human fact acceptance: {identifier}")
        if fact_hash(fact) != fact["content_sha256"] or review["reviewed_content_sha256"] != fact["content_sha256"]:
            raise ValueError(f"Accepted fact content checksum mismatch: {identifier}")
        for provenance in fact["provenance"]:
            source = sources_by_id[provenance["source_id"]]
            source_checksum = canonical_hash({key: value for key, value in source.items() if key not in {"source_record_sha256", "rights_review"}})
            source_review = source["rights_review"]
            if source_checksum != source["source_record_sha256"]:
                raise ValueError(f"Source checksum mismatch: {source['source_id']}")
            if source_review["decision"] != "ACCEPT" or not source_review["checks_confirmed"] or source_review["reviewed_source_record_sha256"] != source_checksum:
                raise ValueError(f"Source rights review is incomplete: {source['source_id']}")
            if provenance["source_record_sha256"] != source_checksum or provenance["source_record_revision"] != source["record_revision"]:
                raise ValueError(f"Fact has a stale source dependency: {identifier}")
            needed_sources.add(source["source_id"])
        selected.append(fact)

    # This release is deliberately narrower than a complete trekking-planning assistant.
    # A new topic/reference needs a separately reviewed scope, not just new file rows.
    scope = {
        "scope_id": "NEPAL-LOCAL-PROTOTYPE-SCOPE-01",
        "release_id": release_id,
        "language": "en",
        "adopted_on": "2026-11-18",
        "scope_adoption": "Assistant-selected first implementation scope under the user's explicit request to finish preparation and develop a local minimal prototype.",
        "not_a_new_human_fact_or_answer_key_acceptance": True,
        "allowed_reference_ids": ["ABC-KT-06", "ABC-WV-CORRIDOR"],
        "allowed_topics": ["publisher-defined walking-day count", "ordered day-stage endpoints", "source-described corridor waypoint order", "named stage connections", "distinguishing reference boundaries"],
        "unsupported_topics": ["day or whole-route distance", "altitude/elevation", "walking hours", "cumulative ascent or descent", "recording dates or year", "Poon Hill access or metrics", "Ama Dablam route metrics", "current permits or fees", "live weather or trail opening", "medical or personal safety suitability", "summit itineraries"],
        "shared_scope_en": "This first English prototype covers only the named ABC-KT-06 itinerary labels and ABC-WV-CORRIDOR route descriptions: walking-day count, stage endpoints, described waypoint order and connections. Keep the two reference types separate. No usable distance, altitude, walking-hour, ascent/descent or recording-date field is included. It does not cover Poon Hill, Ama Dablam route planning, live conditions, fees, medical suitability or summit itineraries. Clarify ambiguous route boundaries and state evidence limits instead of filling gaps. This scope instruction is supplied equally to RAG and no-RAG comparison conditions.",
        "accepted_fact_ids": selected_ids,
        "licence_limit": "A selected-field licence and acceptance do not admit a whole source page, photograph or linked material.",
        "quality_limit": "The corpus is six qualified documentary facts. It is sufficient for pipeline and evidence-handling validation, not proof of comprehensive planning value, route length over 10 km, accident reduction or validated personalization.",
        "metadata_limit": "Original qualification text and source registries remain intact for traceability. A recording-year caveat or prior-register note is not a separately admitted date/measurement fact and must not be used to expand this scope.",
        "retrieval_fact_field_allowlist": ["statement_en", "qualification_en", "scope.reference_id", "scope.walk_start", "scope.walk_finish", "scope.subject"],
        "source_context_field_allowlist": ["title", "publisher", "url", "attribution", "licence_id", "licence_url", "additional_notice", "history_url"],
        "excluded_input_locations": ["evaluation/**", "history/**", "staging/**", "**/*audit*", "**/*.xlsx", "**/*.gpx", "**/*.csv", "whole web pages", "inactive or pending facts"],
    }
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "facts.jsonl").write_bytes(select_original_lines(review_dir / "facts.draft.jsonl", "fact_id", set(selected_ids)))
    (destination / "sources.jsonl").write_bytes(select_original_lines(review_dir / "sources.draft.jsonl", "source_id", needed_sources))
    write_json(destination / "scope.json", scope)
    attribution = [
        "Nepal Trail RAG — first local prototype data attribution",
        f"Release: {release_id}",
        f"Based on: {manifest['release_id']}; selected six human-accepted non-distance records only.",
        "This is a local prototype subset, not a public-service or production safety release.",
        "The licence labels apply to their selected-source material. They do not relicense original project code or model weights.",
        "",
    ]
    for source_id in sorted(needed_sources):
        source = sources_by_id[source_id]
        attribution += [f"{source_id}: {source['attribution']}", f"Licence: {source['licence_id']} — {source['licence_url']}"]
        if source.get("additional_notice"):
            attribution.append("Additional source notice: " + source["additional_notice"])
        if source.get("history_url"):
            attribution.append("Contributor history: " + source["history_url"])
        attribution += ["Subset-specific change: only accepted non-distance day/end-point/corridor records are selected; the original fact payloads and reviewed hashes are unchanged.", ""]
    attribution += ["Source registry history describes earlier checks and limits. Its historical acquisition notes are not new retrieval content.", "Questions, answer keys, scores, audit records, pending facts and excluded measurements must remain outside the retrieval index."]
    (destination / "ATTRIBUTION.txt").write_text("\n".join(attribution) + "\n")
    release = {
        "schema_version": "1.0.0",
        "release_id": release_id,
        "created_on": "2026-11-18",
        "stage": "LOCAL_PROTOTYPE_REVIEWED_SUBSET",
        "local_prototype_use": True,
        "production_ready": False,
        "base_review_release": {"id": manifest["release_id"], "manifest_sha256": file_hash(review_dir / "release_manifest.json")},
        "source_review_file_hashes": {name: file_hash(review_dir / name) for name in ["facts.draft.jsonl", "sources.draft.jsonl", "current_use_registry.audit.jsonl"]},
        "fact_file": "facts.jsonl",
        "source_file": "sources.jsonl",
        "scope_file": "scope.json",
        "attribution_file": "ATTRIBUTION.txt",
        "fact_count": len(selected),
        "source_count": len(needed_sources),
        "allowed_fact_ids": selected_ids,
        "excluded_fact_ids": ["K09"],
        "suspended_fact_ids": ["K01", "K02", "K03", "K04", "K05", "K06"],
        "accepted_fact_hashes": {fact["fact_id"]: fact["content_sha256"] for fact in selected},
        "allowed_source_ids": sorted(needed_sources),
        "source_record_hashes": {source_id: sources_by_id[source_id]["source_record_sha256"] for source_id in sorted(needed_sources)},
        "licence_ids": sorted({sources_by_id[source_id]["licence_id"] for source_id in needed_sources}),
        "licence_notes": "O01 selected fields: CC BY 4.0. O03 adapted text: CC BY-SA 4.0; preserve imported CC BY-SA 3.0-work notice and contributor history. No whole-site or image permission is inferred.",
        "source_lineage_limit": "KeiTreks labels and a community guide are documentary evidence; they are not independent trail surveys or current-condition checks.",
        "files": {name: {"sha256": file_hash(destination / name), "bytes": (destination / name).stat().st_size} for name in ["facts.jsonl", "sources.jsonl", "scope.json", "ATTRIBUTION.txt"]},
        "frozen_origin_preserved": all(file_hash(review_dir / relative) == digest for relative, digest in original_snapshot.items()),
    }
    if not release["frozen_origin_preserved"]:
        raise RuntimeError("Frozen source changed during export.")
    write_json(destination / "manifest.json", release)
    return release


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-dir", type=Path, default=Path(__file__).resolve().parents[2] / "outputs/nepal_review_round3_frozen_20261118")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "release")
    parser.add_argument("--release-id", default="NEPAL-RAG-LOCAL-20261118-01")
    parser.add_argument("--fact-ids", nargs="+", default=list(DEFAULT_FACT_IDS))
    args = parser.parse_args()
    if tuple(args.fact_ids) != DEFAULT_FACT_IDS:
        parser.error("This bootstrap scope is reviewed for its six default facts only. A future release needs a reviewed expanded scope and a separate exporter configuration; do not change IDs without that review.")
    release = export_subset(args.review_dir, args.output, args.release_id, args.fact_ids)
    print(json.dumps({"release_id": release["release_id"], "fact_count": release["fact_count"], "source_count": release["source_count"], "frozen_origin_preserved": release["frozen_origin_preserved"]}))


if __name__ == "__main__":
    main()
