import pytest
from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.main import create_app
from app.service import Assistant


def configuration(tmp_path):
    return Settings(release_dir=ROOT / "data/release", runtime_dir=tmp_path,
                    embedding_mode="hash", model_base_url="http://127.0.0.1:9/v1")


def test_offline_preview_and_baseline_are_honestly_different(tmp_path):
    with TestClient(create_app(configuration(tmp_path))) as client:
        assert client.get("/").status_code == 200
        status = client.get("/api/status").json()
        assert status["indexed_fact_count"] == 6 and not status["model"]["connected"]
        rag = client.post("/api/ask", json={"question": "Where does Day 4 start and end?"}).json()
        assert rag["answer_kind"] == "evidence_preview"
        assert rag["model_id"] is None and rag["evidence"]
        baseline = client.post("/api/ask", json={"question": "Where does Day 4 start and end?", "mode": "baseline"}).json()
        assert baseline["answer_kind"] == "error" and baseline["evidence"] == []


def test_reference_filter_and_unreviewed_references(tmp_path):
    with TestClient(create_app(configuration(tmp_path))) as client:
        body = client.post("/api/ask", json={"question": "Which places lead from Dobhan to MBC?", "reference_id": "ABC-WV-CORRIDOR"}).json()
        assert all(x["reference_id"] == "ABC-WV-CORRIDOR" for x in body["evidence"])
        assert client.post("/api/ask", json={"question": "A valid question", "reference_id": "EBC"}).status_code == 422


def test_original_release_keeps_reviewed_field_limits(tmp_path):
    with TestClient(create_app(configuration(tmp_path))) as client:
        for question in ["How many kilometres is the ABC trek?", "Can I climb Ama Dablam safely tomorrow?", "What elevation is MBC?", "What recording year was it?"]:
            answer = client.post("/api/ask", json={"question": question, "mode": "rag"}).json()
            assert answer["answer_kind"] == "scope_limit"
            assert answer["evidence"] == []


def test_scope_does_not_block_endpoint_comparison(tmp_path):
    engine = Assistant(configuration(tmp_path))
    try:
        assert engine.scope_limit("Compare Deurali to ABC with MBC to ABC. May a measurement for the first be assigned to the second?") is None
        assert engine.scope_limit("How many walking days does the reference have?") is None
    finally:
        engine.close()


def test_control_has_no_document_or_citation_instruction(tmp_path):
    engine = Assistant(configuration(tmp_path))
    try:
        evidence = engine.retriever.search("Siwai walking days", 3)
        rag = engine.messages("What walking days are listed?", evidence)
        baseline = engine.messages("What walking days are listed?", [])
        from app.service import BASE_PROMPT
        assert all(m[0]["content"].startswith(BASE_PROMPT) for m in (rag, baseline))
        assert "[K07]" in rag[1]["content"]
        assert baseline[1] == {"role": "user", "content": "What walking days are listed?"}
        assert all("reviewed sources" not in m["content"] and "[K08]" not in m["content"] for m in baseline)
    finally:
        engine.close()


def test_cross_origin_and_oversized_inputs_rejected(tmp_path):
    with TestClient(create_app(configuration(tmp_path))) as client:
        assert client.post("/api/ask", headers={"Origin": "https://example.org"}, json={"question": "Where is ABC?"}).status_code == 403
        assert client.post("/api/ask", json={"question": "x" * 1201}).status_code == 422
        assert client.post("/api/ask", json={"question": "Where is ABC?", "top_k": 99}).status_code == 422


def test_missing_walking_window_precedes_generation(tmp_path, monkeypatch):
    engine = Assistant(configuration(tmp_path))
    try:
        def unexpected_model_call():
            pytest.fail("A missing walking window should not invoke the generator")

        monkeypatch.setattr(engine.llm, "status", unexpected_model_call)
        result = engine.ask("Can I fit the whole trek into five days including travel?", "rag", None, 3)
        assert result["answer_kind"] == "clarification"
        assert result["planning_step"] == "ASK_WINDOW" and result["model_id"] is None
        assert "trailhead" in result["answer"]
    finally:
        engine.close()


@pytest.mark.parametrize("draft", [
    "The reviewed sources do not give enough information to answer that question. Here is a guess.",
    "The walk is 14 hours.", "The walk is 14 hours [KT-D5-UNKNOWN].",
])
def test_unsupported_completion_preserved_for_audit(tmp_path, monkeypatch, draft):
    from app.service import INSUFFICIENT_EVIDENCE

    engine = Assistant(configuration(tmp_path))
    try:
        monkeypatch.setattr(engine.llm, "status", lambda: {"connected": True})
        monkeypatch.setattr(engine.llm, "complete", lambda messages: {
            "answer": draft, "model_id": "test", "finish_reason": "stop",
        })
        result = engine.ask("Which route starts in Siwai?", "rag", None, 3)
        assert result["answer_kind"] == "scope_limit"
        assert result["answer"] == INSUFFICIENT_EVIDENCE
        assert result["raw_answer"] == draft and result["warnings"] == []
    finally:
        engine.close()

def test_baseline_uses_own_dialogue_and_skips_route_resolution(tmp_path, monkeypatch):
    with TestClient(create_app(configuration(tmp_path))) as client:
        assistant = client.app.state.assistant
        messages = []
        monkeypatch.setattr(client.app.state.subjects, "resolve", lambda *a: pytest.fail("private route expansion"))
        monkeypatch.setattr(assistant.retriever, "search", lambda *a: pytest.fail("unexpected retrieval"))
        monkeypatch.setattr(assistant.llm, "status", lambda: {"connected": True})
        def complete(prompt):
            messages.extend(prompt)
            return {"answer": "A model answer.", "model_id": "test-model"}
        monkeypatch.setattr(assistant.llm, "complete", complete)
        question = "Can I fit the whole trek into five days including travel?"
        result = client.post("/api/ask", json={"mode": "baseline", "question": question, "offer_live_checks": True,
            "baseline_history": [{"question": "I walk with my sister.", "answer": "Understood."}]}).json()
        assert result["answer_kind"] == "llm" and result["evidence"] == []
        assert messages[1:] == [{"role": "user", "content": "I walk with my sister."},
                                {"role": "assistant", "content": "Understood."}, {"role": "user", "content": question}]
