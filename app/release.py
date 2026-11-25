"""Manifest-only data loading. Audit/history directories are never traversed."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


def canonical_hash(value: dict) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode()).hexdigest()


def fact_content_hash(fact: dict) -> str:
    core = {k: v for k, v in fact.items() if k not in {"content_sha256", "review"}}
    core["governance"] = {
        k: v for k, v in fact["governance"].items()
        if k not in {"release_review_status", "production_eligible"}
    }
    return canonical_hash(core)


def source_content_hash(source: dict) -> str:
    return canonical_hash({
        k: v for k, v in source.items() if k not in {"source_record_sha256", "rights_review"}
    })


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@dataclass
class Release:
    manifest: dict
    facts: list[dict]
    sources: dict[str, dict]
    scope: dict
    chunks: list[dict]

    def index_fingerprint(self, embedding_identity: str) -> str:
        return canonical_hash({
            "release": self.manifest, "embedding": embedding_identity,
            "chunk_schema": "atomic-reviewed-v1", "chunks": self.chunks,
        })[:20]


def load_release(directory: Path) -> Release:
    directory = directory.resolve()
    manifest = json.loads((directory / "manifest.json").read_text())
    if not manifest.get("local_prototype_use") or manifest.get("production_ready"):
        raise ValueError("A reviewed local-prototype manifest is required.")
    files = manifest["files"]
    required = {manifest[k] for k in ("fact_file", "source_file", "scope_file", "attribution_file")}
    if not required <= set(files):
        raise ValueError("Manifest is missing required file digests.")
    for name, item in files.items():
        path = (directory / name).resolve()
        if path.parent != directory or path.suffix in {".xlsx", ".gpx", ".csv"}:
            raise ValueError("Release files must be explicitly named flat files.")
        raw = path.read_bytes()
        if len(raw) != item["bytes"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError(f"File integrity failed: {name}")
    facts = read_jsonl(directory / manifest["fact_file"])
    source_rows = read_jsonl(directory / manifest["source_file"])
    scope = json.loads((directory / manifest["scope_file"]).read_text())
    sources = {s["source_id"]: s for s in source_rows}
    ids = [f["fact_id"] for f in facts]
    if len(set(ids)) != len(ids) or len(facts) != manifest["fact_count"]:
        raise ValueError("Duplicate fact IDs or wrong fact count.")
    if set(ids) != set(manifest["allowed_fact_ids"]):
        raise ValueError("Fact file does not match the explicit ID allowlist.")
    if len(sources) != len(source_rows) or len(sources) != manifest["source_count"]:
        raise ValueError("Duplicate source IDs or wrong source count.")
    if set(sources) != set(manifest["allowed_source_ids"]):
        raise ValueError("Source file does not match the allowlist.")
    blocked = set(manifest.get("excluded_fact_ids", [])) | set(manifest.get("suspended_fact_ids", []))
    if set(ids) & blocked:
        raise ValueError("Inactive facts cannot enter the release.")
    for source in source_rows:
        digest = source_content_hash(source)
        review = source["rights_review"]
        if digest != source["source_record_sha256"] or digest != manifest["source_record_hashes"][source["source_id"]]:
            raise ValueError("Source record digest mismatch.")
        if not (review["decision"] == "ACCEPT" and review["reviewer"] and review["checks_confirmed"]
                and review["reviewed_source_record_sha256"] == digest):
            raise ValueError("Source rights review is incomplete.")
        if not source.get("licence_id") or not source.get("attribution"):
            raise ValueError("Missing licence or attribution.")
    chunks = []
    for fact in facts:
        digest = fact_content_hash(fact)
        review = fact["review"]
        if digest != fact["content_sha256"] or digest != manifest["accepted_fact_hashes"][fact["fact_id"]]:
            raise ValueError("Fact content digest mismatch.")
        if not (review["decision"] == "ACCEPT" and review["reviewer"] and review["checks_confirmed"]
                and review["reviewed_content_sha256"] == digest
                and fact["governance"]["release_review_status"] == "HUMAN_ACCEPTED"):
            raise ValueError("Unreviewed factual record.")
        if set(fact["dependencies"]["required_fact_ids"]) - set(ids):
            raise ValueError("Incomplete fact dependency.")
        if fact["dependencies"]["bundle_ids"]:
            raise ValueError("This prototype release must not split an unresolved conflict bundle.")
        if fact["scope"]["reference_id"] not in scope["allowed_reference_ids"]:
            raise ValueError("Fact falls outside the release scope.")
        if not fact["statement_en"].strip() or len(fact["statement_en"]) > 4000:
            raise ValueError("Fact is empty or too long for an atomic reviewed chunk.")
        if not fact["provenance"]:
            raise ValueError("A fact needs at least one reviewed source.")
        source_records = []
        for provenance in fact["provenance"]:
            source = sources.get(provenance["source_id"])
            if source is None:
                raise ValueError("Missing source dependency.")
            if provenance["source_record_sha256"] != source["source_record_sha256"] or provenance["source_record_revision"] != source["record_revision"]:
                raise ValueError("Stale source dependency.")
            source_records.append({
                "source_id": source["source_id"], "source_title": source["title"],
                "source_url": source["url"], "source_locator": provenance["source_locator"],
                "source_revision": provenance["source_revision"], "licence_id": source["licence_id"],
                "licence_url": source["licence_url"], "attribution": source["attribution"],
                "additional_notice": source.get("additional_notice"), "history_url": source.get("history_url"),
            })
        ref = fact["scope"]["reference_id"]
        text = f"Reference: {ref}\n{fact['statement_en']}\nQualification: {fact['qualification_en']}"
        chunks.append({
            "chunk_id": f"{fact['fact_id']}@{digest[:12]}", "fact_id": fact["fact_id"],
            "content_sha256": digest, "reference_id": ref, "text": text,
            **source_records[0], "source_records": source_records,
        })
    return Release(manifest, facts, sources, scope, chunks)
