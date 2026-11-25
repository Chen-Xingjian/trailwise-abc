import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.main import create_app
from app.variant_plans import RECORDS, counts


@pytest.fixture
def ask(tmp_path):
    app = create_app(Settings(release_dir=ROOT / "documents/abc-six-day", runtime_dir=tmp_path))
    with (
        TestClient(app) as client,
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as offline,
    ):
        app.state.public_sources = offline

        def query(q, prior=None):
            prior = prior or {}
            response = client.post(
                "/api/ask",
                json=dict(
                    question=q,
                    offer_live_checks=True,
                    prior_plan=prior.get("planning_budget", {} if prior.get("answer_kind") == "variant_plan" else None),
                    planning_followup=prior.get("answer_kind") in {"clarification", "itinerary_budget"},
                    variant_context=prior.get("variant_context"),
                    trail_focus=prior.get("trail_focus"),
                    distance_followup=prior.get("answer_kind") == "route_distance",
                ),
            )
            response.raise_for_status()
            return response.json()

        yield query


def test_budget_and_daily_followup(ask):
    one = ask("I have five days. Which ABC route should I take?")
    assert "If your 5 days start and end in Pokhara" in one["answer"]
    assert "no reserve" in one["answer"] and "Are these walking days" in one["answer"]
    two = ask("Five net walking days.", one)
    assert "For 5 walking days" in two["answer"] and "Are these walking days" not in two["answer"]
    three = ask("Show me the daily itinerary.", two)
    assert (
        "Day 5 · Walk Sinuwa → Jhinu Danda" in three["answer"]
        and len(three["itinerary_sources"]) == 1
    )
    outside = ask("Five days including flights from Kathmandu.", one)
    assert (
        "outside Pokhara" in outside["answer"] and outside["variant_context"]["basis"] == "travel"
    )


def test_counts_and_source_links():
    assert {
        k: (*counts(r), len(r["days"]) if r["pokhara_return_documented"] else None)
        for k, r in RECORDS.items()
    } == {
        "jhinu": (5, 2, 5),
        "siwai": (6, 0, None),
        "ghandruk": (6, 1, 7),
        "nayapul": (7, 2, 7),
        "poon": (7, 1, 8),
    }


def test_screenshot_branch_and_specific_budget(ask):
    first = ask("How far is the Annapurna Base Camp trek?")
    second = ask("From Nayapul/Birethanti", first)
    assert second["answer_kind"] == "route_distance" and "Nayapul" in second["answer"]
    answer = ask("I have five days. Is this route suitable?", second)
    assert "7 days from Pokhara" in answer["answer"] and "change trailheads" in answer["answer"]
    assert len(answer["itinerary_sources"]) == 2
    plan = ask("Show me the daily plan for Nayapul.")
    assert "Day 7 · Walk Jhinu Hot Spring → Nayapul" in plan["answer"]

def test_expand_default_budget_into_observed_daily_stages(ask):
    first = ask("can you give me a plan for ABC trek")
    assert first["planning_budget"] == {"days": 5, "origin": "default"}
    for q in ("can you give me a detailed plan", "Could you break it down day by day?"):
        reply = ask(q, first)
        assert reply["variant_context"]["keys"] == ["siwai"]
        assert "5 walking days were an example" in reply["answer"]
        assert reply["answer"].count("- Day ") == 6
        assert "4h 30m moving, 7h 43m including stops" in reply["answer"]
        cited = {c["fact_id"] for c in reply["evidence"]}
        assert {f"KT-D{d}-{clock}" for d in range(1, 7) for clock in "ME"} <= cited


def test_detail_retains_requested_budget_and_alternative_trailhead(ask):
    first = ask("Plan my ABC trek from Siwai for seven walking days")
    assert "1 in reserve" in ask("Can you flesh that out?", first)["answer"]
    village = ask("Show me the daily itinerary from Ghandruk")
    reply = ask("Could I have a more detailed plan?", village)
    assert reply["variant_context"]["keys"] == ["ghandruk"]
    assert "5–6 hours" in reply["answer"] and not reply["evidence"]
    assert "KeiTreks" not in reply["answer"]
    assert ask("Give me a detailed packing list", first)["answer_kind"] != "variant_plan"


@pytest.mark.parametrize(("key", "questions", "number", "leg", "extra"), [
    ('jhinu', ['Could I get a quick overview of the ABC trek from Jhinu Danda?', 'Can you give me a detailed plan?', 'What’s on the fourth day?'], 4, 'ABC → Sinuwa', '6–8'),
    ('siwai', ['Can you give me a plan for ABC trek from Siwai?', 'Could you lay it out day by day?', 'Walk me through day four.'], 4, 'Deurali → ABC', '1,000'),
    ('ghandruk', ["What's the ABC itinerary from Ghandruk in a nutshell?", 'Can you flesh that out?', "What's the plan for the first walking day?"], 2, 'Ghandruk → Chhomrong', '5–6'),
    ('nayapul', ['Can you outline the ABC itinerary from Nayapul?', 'Show me the full itinerary, please.', 'How does the final day work, including getting back to Pokhara?'], 7, 'Jhinu Hot Spring → Nayapul', 'Nayapul → Pokhara'),
    ('poon', ['Give me the big picture for the ABC trek via Poon Hill.', 'Could I see what happens each day?', 'What do we do on day one?'], 1, 'Pokhara → Ghorepani', 'transfer day'),
])
def test_itinerary_drilldown(ask, key, questions, number, leg, extra):
    overview = ask(questions[0])
    assert overview["answer_kind"] in {"variant_plan", "itinerary_budget"}
    assert "Day 1 ·" not in overview["answer"]
    details = ask(questions[1], overview)
    assert details["answer"].count("- Day ") == len(RECORDS[key]["days"])
    assert details["variant_context"]["keys"] == [key]
    stage = ask(questions[2], details)
    assert stage["variant_context"]["keys"] == [key]
    assert stage["variant_context"]["stage"] == number
    assert leg in stage["answer"] and extra in stage["answer"]
    assert stage["answer"].count(" · ") == 1 and "Walking endpoints" not in stage["answer"]
    for answer in (details, stage):
        assert [s["url"] for s in answer["itinerary_sources"]] == [RECORDS[key]["url"]]
        if key != "siwai":
            assert not answer["evidence"]
    if key == "nayapul":
        other = ask("What happens on day two when we leave Ghandruk?", details)
        assert other["variant_context"]["keys"] == ["nayapul"]
        assert "Ghandruk → Sinuwa" in other["answer"]
