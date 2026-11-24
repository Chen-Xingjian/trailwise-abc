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
