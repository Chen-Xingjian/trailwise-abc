"""Prepare the first development protocol; never simulate model runs or scores."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT.parent / "outputs/nepal_review_round3_frozen_20261118"
SELECTED = ("D01", "D02", "D03", "D04", "D06", "D08", "D09", "D12")


def main() -> None:
    source_path = REVIEW / "development_set.draft.json"
    source = json.loads(source_path.read_text())
    release = json.loads((ROOT / "data/release/manifest.json").read_text())
    allowed = set(release["allowed_fact_ids"])
    by_id = {item["item_id"]: item for item in source["items"]}
    questions = []
    for identifier in SELECTED:
        item = deepcopy(by_id[identifier])
        if not set(item["required_fact_ids"]).issubset(allowed):
            raise ValueError(f"Question needs unaccepted or excluded evidence: {identifier}")
        if item["required_bundle_ids"]:
            raise ValueError("The first subset does not include conflict bundles.")
        item.pop("change_summary_en", None)
        item["source_item_id"] = identifier
        item["comparison_group"] = "FACTUAL" if item["score_group"] == "ANSWERABLE" else "BOUNDARY"
        item["scope_evidence_ids"] = ["NEPAL-LOCAL-PROTOTYPE-SCOPE-01"] if item["scope_evidence_ids"] else []
        item["availability_status"] = "ACCEPTED_FACT_PREREQUISITES_PENDING_IMPLEMENTATION_PREFLIGHT"
        item["required_fact_acceptance_complete"] = True
        item["awaiting_fact_acceptance"] = []
        item["executed"] = False
        item["executable_now"] = False
        item["content_score"] = None
        item["reference_answer_human_review_recorded"] = False
        item["release_conditions"] = [
            "Use this exact six-fact release and implementation scope in both conditions.",
            "Perform a genuine configured-model health check; no preview, mock or canned answer counts as an LLM run.",
            "Log the model identifier, quantization where known, generation settings, release checksum and actual retrieved IDs.",
            "Keep content grading separate from retrieval/citation diagnostics; human content scores remain pending until reviewed.",
        ]
        for evidence in item["evidence"]:
            fact_id = evidence["fact_id"]
            if evidence["current_candidate_fact_sha256"] != release["accepted_fact_hashes"][fact_id]:
                raise ValueError(f"Question points to changed factual content: {identifier}/{fact_id}")
        questions.append(item)
    factual = [q for q in questions if q["comparison_group"] == "FACTUAL"]
    boundary = [q for q in questions if q["comparison_group"] == "BOUNDARY"]
    assert len(factual) == 6 and len(boundary) == 2
    assert sum(q["scoring"]["maximum_points"] for q in questions) == 24
    protocol = {
        "schema_version": "1.0.0",
        "dataset_id": "NEPAL-LOCAL-DEV-20261118-01",
        "created_on": "2026-11-18",
        "data_release_id": release["release_id"],
        "source_review_release_id": source["review_release_id"],
        "source_development_file_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "implementation_scope_id": "NEPAL-LOCAL-PROTOTYPE-SCOPE-01",
        "implementation_scope_path": "data/release/scope.json",
        "protocol_adoption": "Assistant implementation choice under the user's explicit request to finish the two preparation steps and develop the local minimal prototype; this is not a new human acceptance of individual reference answers.",
        "human_reference_answer_acceptance_recorded": False,
        "generation_runs_authorized_as_local_development": True,
        "execution_state": "NOT_RUN",
        "executed": False,
        "final_test_set": False,
        "retrieval_use": False,
        "selected_item_ids": list(SELECTED),
        "item_count": 8,
        "maximum_points": 24,
        "score_groups": {
            "FACTUAL": {"count": 6, "maximum_points": 18},
            "BOUNDARY": {"count": 2, "maximum_points": 6},
        },
        "fair_comparison_rules": [
            "Use the same actual local generation model, quantization, shared scope instruction, question wording, generation parameters and output budget.",
            "Neither condition browses or receives live weather; only the RAG condition receives retrieved evidence.",
            "Use the same corpus-independent scope limits and ambiguity rules in both conditions.",
            "Score factual content using the same three-point criteria. Do not penalize baseline for lacking retrieved citations.",
            "Report six factual items and two boundary items separately. Boundary compliance alone does not demonstrate retrieval improvement.",
            "Measure RAG retrieval coverage and supported citations separately; a citation existing does not establish that it supports a claim.",
            "A preview or deterministic scope message is not an LLM response and must not be reported as a model-comparison result.",
            "Missing or failed runs stay missing, not zero-scored successes; do not fill manual grades automatically.",
            "Keep this file, reference answers, rubrics and human scores outside the retrieval corpus.",
            "Use a separately checked unseen final set later. These questions are development material and are not evidence of general route-planning accuracy.",
        ],
        "metrics": {
            "shared_content": "Manual 0–3 score per item with the listed material-error rule; report factual subtotal /18 and boundary subtotal /6 separately.",
            "rag_only": ["required-fact coverage at fixed top_k", "citation support correctness", "unsupported factual claims", "latency"],
            "results": None,
        },
        "items": questions,
    }
    (ROOT / "evaluation/development.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"dataset_id": protocol["dataset_id"], "items": 8, "maximum_points": 24, "executed": False}))


if __name__ == "__main__":
    main()
