from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.main import create_app
from app.release import load_release
from app.turn_context import TrailFocus, TrailSubjects

CORPUS = ROOT / "documents/abc-six-day"


def test_branch_focus_direction_and_place_changes():
    subjects = TrailSubjects(load_release(CORPUS))
    left, _ = subjects.resolve("Tell me about day 4 of the ABC trek.", None, None)
    right, _ = subjects.resolve("How about Bamboo to Siwai?", left, None)
    assert left.places == ["Deurali", "Annapurna Base Camp"]
    assert right.places == ["Bamboo", "Siwai"]
    for parent in (left, right):
        assert " to ".join(parent.places) in subjects.resolve("How much ascent?", parent, None)[1]
    reverse, _ = subjects.resolve("And the other way?", left, None)
    assert reverse.places == left.places[::-1]
    assert subjects.resolve("And at Deurali?", right, None)[0].places == ["Deurali"]
    assert not subjects.resolve("How about Everest?", left, None)[0].places
    assert "invented" not in subjects.resolve("How far?", TrailFocus(places=["invented"]), None)[1]


def test_context_api_preserves_planning_and_weather_slots(tmp_path):
    with TestClient(create_app(Settings(release_dir=CORPUS, runtime_dir=tmp_path))) as client:
        def ask(text, **kwargs):
            return client.post("/api/ask", json={"question": text, "offer_live_checks": True, **kwargs}).json()

        plan = ask("Plan my ABC trek from Siwai.")
        follow = ask("Make it seven days.", trail_focus=plan["trail_focus"], planning_followup=True)
        assert follow["planning_budget"]["days"] == 7
        first = ask("Plan my ABC trek with five days including travel.")
        second = ask("I start walking Monday afternoon.", prior_planning_question=first["planning_question"],
                     planning_followup=True, trail_focus=first["trail_focus"])
        assert second["planning_step"] == "ASK_FINISH"
        result = ask("What's the weather there?", trail_focus={"places": ["Deurali"]})
        assert result["answer_kind"] == "live_clarification" and result["chat_context"]["point"] == "Deurali"
