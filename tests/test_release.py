import copy
import hashlib
import json
import shutil

import pytest

from app.config import ROOT
from app.release import fact_content_hash, load_release


@pytest.fixture
def release_copy(tmp_path):
    target = tmp_path / "release"
    shutil.copytree(ROOT / "data/release", target)
    return target


def update_facts(directory, facts, manifest=None):
    path = directory / "facts.jsonl"
    path.write_text("".join(json.dumps(f, ensure_ascii=False) + "\n" for f in facts))
    manifest = manifest or json.loads((directory / "manifest.json").read_text())
    manifest["files"]["facts.jsonl"] = {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))


def test_release_is_only_reviewed_non_distance_subset():
    release = load_release(ROOT / "data/release")
    assert {f["fact_id"] for f in release.facts} == {"K07", "K08", "W01", "W02", "W03", "W04"}
    assert len(release.chunks) == 6
    assert all("prior_register" not in c["text"] for c in release.chunks)
    assert all(c["licence_id"] and c["source_locator"] for c in release.chunks)


def test_changed_bytes_fail_before_ingestion(release_copy):
    with (release_copy / "facts.jsonl").open("a") as f:
        f.write("{}\n")
    with pytest.raises(ValueError, match="integrity"):
        load_release(release_copy)


def test_pending_record_cannot_be_smuggled_by_updating_file_digest(release_copy):
    release = load_release(release_copy)
    facts = copy.deepcopy(release.facts)
    facts[0]["review"]["decision"] = "PENDING"
    update_facts(release_copy, facts)
    with pytest.raises(ValueError, match="Unreviewed"):
        load_release(release_copy)


def test_changed_fact_invalidates_old_review_even_with_new_manifest(release_copy):
    release = load_release(release_copy)
    facts = copy.deepcopy(release.facts)
    facts[0]["statement_en"] += " Changed text."
    facts[0]["content_sha256"] = fact_content_hash(facts[0])
    manifest = copy.deepcopy(release.manifest)
    manifest["accepted_fact_hashes"][facts[0]["fact_id"]] = facts[0]["content_sha256"]
    update_facts(release_copy, facts, manifest)
    with pytest.raises(ValueError, match="Unreviewed"):
        load_release(release_copy)


def test_inactive_id_is_blocked_even_if_allowlisted(release_copy):
    release = load_release(release_copy)
    facts = copy.deepcopy(release.facts)
    facts[0]["fact_id"] = "K09"
    manifest = copy.deepcopy(release.manifest)
    manifest["allowed_fact_ids"][0] = "K09"
    update_facts(release_copy, facts, manifest)
    with pytest.raises(ValueError, match="Inactive"):
        load_release(release_copy)


def test_manifest_cannot_escape_release_directory(release_copy):
    manifest = json.loads((release_copy / "manifest.json").read_text())
    manifest["files"]["../secret.json"] = {"sha256": "0", "bytes": 0}
    (release_copy / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="flat files"):
        load_release(release_copy)


def test_secondary_source_is_also_hash_checked(release_copy):
    release = load_release(release_copy)
    facts = copy.deepcopy(release.facts)
    second = copy.deepcopy(facts[0]["provenance"][0])
    second["source_record_sha256"] = "0" * 64
    facts[0]["provenance"].append(second)
    digest = fact_content_hash(facts[0])
    facts[0]["content_sha256"] = digest
    facts[0]["review"]["reviewed_content_sha256"] = digest
    manifest = copy.deepcopy(release.manifest)
    manifest["accepted_fact_hashes"][facts[0]["fact_id"]] = digest
    update_facts(release_copy, facts, manifest)
    with pytest.raises(ValueError, match="Stale source"):
        load_release(release_copy)


def test_new_reviewed_version_has_no_permanent_six_record_cap(release_copy):
    release = load_release(release_copy)
    facts = copy.deepcopy(release.facts)
    # Synthetic fixture: an already-reviewed sentence in a new version/ID, not new trail evidence.
    new = copy.deepcopy(facts[0])
    new["fact_id"] = "TEST-EXTENSION-01"
    new["record_uid"] = "urn:test:extension-01"
    new["record_revision"] += 1
    new["content_sha256"] = fact_content_hash(new)
    new["review"]["reviewed_content_sha256"] = new["content_sha256"]
    facts.append(new)
    manifest = copy.deepcopy(release.manifest)
    manifest["fact_count"] += 1
    manifest["allowed_fact_ids"].append(new["fact_id"])
    manifest["accepted_fact_hashes"][new["fact_id"]] = new["content_sha256"]
    update_facts(release_copy, facts, manifest)
    assert len(load_release(release_copy).chunks) == 7
