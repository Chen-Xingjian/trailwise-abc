import pytest
from fastapi.testclient import TestClient

from app.citations import citation_ids
from app.config import ROOT, Settings
from app.main import create_app
from app.packing import packing_answer
from app.release import load_release

CORPUS = ROOT / "documents/abc-six-day"


def test_packing_after_planning_uses_equipment_sources(tmp_path):
    with TestClient(create_app(Settings(release_dir=CORPUS, runtime_dir=tmp_path))) as client:

        def ask(q, **extra):
            return client.post(
                "/api/ask", json={"question": q, "offer_live_checks": True, **extra}
            ).json()

        plan = ask("Can you plan my Annapurna Base Camp trek from Siwai?")
        response = ask(
            "what should I bring for this trip",
            planning_followup=True,
            trail_focus=plan["trail_focus"],
        )
        assert response["answer_kind"] == "packing_list"
        assert "Siwai" in response["answer"] and "If current local reports" in response["answer"]
        ids = {c["fact_id"] for c in response["evidence"]}
        assert ids == citation_ids(response["answer"]) and {"G02", "G06", "G07", "G08"} <= ids
        assert all(i.startswith("G") for i in ids)
        assert not ask("what should I bring for this trip", mode="baseline")["evidence"]


@pytest.mark.parametrize(
    "question",
    [
        "What gear do I need for this hike?",
        "Can you give me a packing list?",
        "What should we pack for the ABC trek?",
        "What to bring?",
    ],
)
def test_common_packing_phrasings(question):
    assert packing_answer(question, load_release(CORPUS), "ABC-KT-06")


@pytest.mark.parametrize(
    "question",
    [
        "What temperature rating should I bring for my sleeping bag?",
        "What should I bring for this trek and is the trail open?",
        "What should I bring for Everest?",
        "What do I need to bring for a knee injury?",
    ],
)
def test_specialized_questions_keep_their_own_evidence(question):
    assert packing_answer(question, load_release(CORPUS), None) is None


def test_clock_definitions_minutes_and_pack_rain(tmp_path):
    with TestClient(create_app(Settings(release_dir=CORPUS, runtime_dir=tmp_path))) as client:
        def ask(q):
            return client.post("/api/ask", json={"question": q, "offer_live_checks": True}).json()

        definitions = ask("What is the difference between moving time and elapsed time on a trek?")
        assert "Stops are excluded" in definitions["answer"] and "including stops" in definitions["answer"]
        assert len(definitions["evidence"]) == 2
        rain = ask("What should I pack to keep my gear dry on the Annapurna Base Camp trek?")
        assert "inside" in rain["answer"] and rain["evidence"][0]["source_url"].startswith("https://www.nps.gov/")
        minutes = ask("In the KeiTreks six-day log, exactly how many minutes did the Deurali to ABC stage take including stops?")
        assert "463 minutes" in minutes["answer"] and citation_ids(minutes["answer"]) == {"KT-D4-E"}
        reverse = ask("How many minutes including stops did KeiTreks take from ABC to Deurali?")
        assert "463" not in reverse["answer"]
