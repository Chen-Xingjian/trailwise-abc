"""Evaluation bookkeeping checks; fixtures never become development run results."""

import csv
import json

import pytest

from scripts.run_development import DEFAULT_DATASET, diagnostic, write_grading


@pytest.fixture
def development_items():
    dataset = json.loads(DEFAULT_DATASET.read_text())
    return {item["item_id"]: item for item in dataset["items"]}


@pytest.mark.parametrize("item_id", ["D01", "D12"])
def test_grading_preserves_protocol_critical_errors_and_leaves_scores_blank(
    tmp_path, development_items, item_id
):
    item = development_items[item_id]
    record = {
        "item_id": item_id,
        "comparison_group": item["comparison_group"],
        "mode": "rag",
        "answer_kind": "error",
        "response_class": "MISSING_OR_FAILED_RESPONSE",
        "answer": "",
        "retrieval_diagnostic": diagnostic(item, "rag", {"answer_kind": "error"}),
    }
    output = tmp_path / "grading.csv"
    write_grading(output, [record], development_items)

    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    row = rows[0]
    assert row["critical_error"] == item["scoring"]["critical_error"]
    assert row["critical_error_override"] == item["scoring"]["critical_error_override"]
    assert row["human_score"] == ""
    assert row["human_notes"] == ""
    assert row["answer"] == ""


def test_boundary_policy_does_not_receive_a_retrieval_score(development_items):
    item = development_items["D09"]
    assert item["comparison_group"] == "BOUNDARY" and item["required_fact_ids"]
    # Even complete ID overlap is not model retrieval evidence for a policy reply.
    response = {
        "answer_kind": "scope_limit",
        "evidence": [{"fact_id": fact_id} for fact_id in item["required_fact_ids"]],
    }
    result = diagnostic(item, "rag", response)
    assert result["required_fact_recall_at_k"] is None
    assert result["citation_support_correctness"] is None


def test_retrieval_diagnostic_distinguishes_model_and_policy_responses(development_items):
    item = development_items["D01"]
    evidence = [{"fact_id": fact_id} for fact_id in item["required_fact_ids"]]
    model_result = diagnostic(item, "rag", {"answer_kind": "llm", "evidence": evidence})
    policy_result = diagnostic(item, "rag", {"answer_kind": "scope_limit", "evidence": evidence})
    baseline_result = diagnostic(item, "baseline", {"answer_kind": "llm", "evidence": []})
    assert model_result["required_fact_recall_at_k"] == 1.0
    assert policy_result["required_fact_recall_at_k"] is None
    assert baseline_result["required_fact_recall_at_k"] is None
    assert model_result["citation_support_correctness"] is None


def test_stage_climate_and_preparation_citations_are_checked_in_groups():
    supplied = ["KT-D4-ASC-APPROX", "S05-ABC-07", "F04"]
    result = diagnostic({}, "rag", {
        "answer_kind": "llm", "answer": "[KT-D4-ASC-APPROX, S05-ABC-07] [F04] [KT-D4-FAKE]",
        "evidence": [{"fact_id": fid} for fid in supplied],
    })
    assert set(result["citation_ids"]) == set(supplied) | {"KT-D4-FAKE"}
    assert result["citations_not_in_supplied_evidence"] == ["KT-D4-FAKE"]
