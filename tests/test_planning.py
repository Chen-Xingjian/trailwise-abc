import pytest

from app.planning import checked_window_summary, planning_step

PLAN = "I have five days including travel. Can I fit the full trek? "


@pytest.mark.parametrize(("update", "step"), [
    ("", "ASK_WINDOW"),
    ("My flight arrives Monday at 13:00 and departs Friday at 11:00.", "ASK_WINDOW"),
    ("My outbound flight leaves the city Friday at 11:00 after visiting the trailhead.", "ASK_WINDOW"),
    ("I can start walking on Monday afternoon.", "ASK_FINISH"),
    ("My jeep leaves Siwai on Friday at 11:00.", "ASK_START"),
    ("I can start walking on Monday afternoon and finish walking on Friday morning.", "PLAN"),
    ("We have three full walking days after transfers.", "PLAN"),
    ("I can hike Tuesday through Thursday.", "PLAN"),
])
def test_user_supplied_window(update, step):
    assert planning_step(PLAN + update, {"Siwai"}) == step


def test_partial_information_and_unrelated_queries():
    assert planning_step("Can I fit the full ABC trek into five days?", set()) == "ASK_WINDOW"
    assert planning_step("Where did the day six track finish?", set()) is None


def test_window_summary_preserves_user_times_and_cites_only_supplied_facts():
    question = PLAN + "I start walking Monday at 13:00 and finish walking Friday at 11:00."
    facts = [{"fact_id": "K07", "predicate": "walking_day_count", "statement_en": "The reference has six walking days.",
              "value": {"number": 6}}]
    approved = "The reference has six walking days [K07]."
    assert checked_window_summary(question, approved, facts) is None
    for draft in ("You have four available walking days.", "Your window leaves six hiking days."):
        answer = checked_window_summary(question, draft, facts)
        assert "Monday at 13:00" in answer and "Friday at 11:00" in answer
        assert "four available" not in answer and "leaves six" not in answer
        assert "[K07]" in answer and "[F03]" not in answer


@pytest.mark.parametrize(("question", "expected"), [
    ("Plan my Annapurna Base Camp trek from Siwai.", ("default", 5)),
    ("Give me an ABC itinerary. I have no time limit.", ("default", 5)),
    ("Plan my trek.", ("default", 5)),
    ("Build a six-day ABC itinerary.", ("requested", 6)),
    ("Plan the ABC trek. I have seven full walking days after transfers.", ("requested", 7)),
    ("Plan my ABC trip in five days including travel.", ("window", "ASK_WINDOW")),
    ("Plan my ABC trip. I start walking Monday afternoon.", ("window", "ASK_FINISH")),
    ("Plan my ABC trip. I start walking Monday afternoon and finish walking Friday morning.", ("window", "PLAN")),
    ("Can I plan for 3 to 5 days on the ABC trek?", ("window", "ASK_WINDOW")),
    ("How many days does the published ABC itinerary take?", None),
    ("Should I pack trekking poles?", None),
    ("What distance should I plan for on the ABC trek?", None),
    ("Can you plan my Everest trek?", None),
])
def test_optional_itinerary_length(question, expected):
    from app.planning import itinerary_request

    assert itinerary_request(question, {"Siwai"}, False) == expected


def test_personal_budget_can_replace_default_in_chat(tmp_path):
    from fastapi.testclient import TestClient

    from app.config import ROOT, Settings
    from app.main import create_app

    with TestClient(create_app(Settings(release_dir=ROOT / "documents/abc-six-day", runtime_dir=tmp_path))) as client:
        def ask(q, **kwargs):
            return client.post("/api/ask", json={"question": q, **kwargs}).json()

        first = ask("Please plan my ABC trek.")
        assert first["planning_budget"] == {"days": 5, "origin": "default"}
        assert "1 day short" in first["answer"] and "6-day reference" in first["answer"]
        assert [x["fact_id"] for x in first["evidence"]] == ["K07", "K08"]
        assert ask("Make it six days.", planning_followup=True)["planning_budget"]["days"] == 6
        spare = ask("Actually, seven days.", planning_followup=True, top_k=1)
        assert "1 day in reserve" in spare["answer"] and len(spare["evidence"]) == 1
        assert ask("Make it five days including travel.", planning_followup=True)["planning_step"] == "ASK_WINDOW"
        assert "planning_budget" not in ask("Make it six days.")
        assert "planning_budget" not in ask("Plan my ABC trek", reference_id="ABC-WV-CORRIDOR")
