import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.main import create_app


@pytest.fixture
def ask(tmp_path):
    app = create_app(Settings(release_dir=ROOT / "documents/abc-six-day", runtime_dir=tmp_path))
    with (
        TestClient(app) as client,
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as offline,
    ):
        app.state.public_sources = offline

        def send(question, parent=None):
            parent = parent or {}
            r = client.post(
                "/api/ask",
                json=dict(
                    question=question,
                    offer_live_checks=True,
                    trail_focus=parent.get("trail_focus"),
                    variant_context=parent.get("variant_context"),
                    chat_context=parent.get("chat_context"),
                    distance_followup=parent.get("answer_kind") == "route_distance",
                ),
            )
            r.raise_for_status()
            return r.json()

        yield send


def test_parallel_replies_keep_their_own_route_and_stage(ask):
    root = ask("I have five walking days. Which route would suit me?")
    jhinu = ask("Show me day 4.", root)
    assert jhinu["trail_focus"]["places"] == ["Annapurna Base Camp", "Sinuwa"]
    equipment = ask("What should I bring?", jhinu)
    assert equipment["variant_context"] == jhinu["variant_context"]
    assert "ABC → Sinuwa" in ask("Show day 4 again.", equipment)["answer"]
    other = ask("Switch to Ghandruk instead.", root)
    assert "Ghandruk → Chhomrong" in ask("Show me day 2.", other)["answer"]
    assert "7–8 hours" in ask("How long was that descent?", jhinu)["answer"]
    outside = ask("What about Everest?", other)
    assert "Everest" in ask("What are its stages?", outside)["answer"].title()
    assert "Ghandruk → Chhomrong" in ask("Show the Ghandruk itinerary.", outside)["answer"]


def test_weather_topic_switches_and_combinations(ask):
    forecast = ask("Forecast at Deurali tomorrow?")
    assert forecast["live"]["status"] == "unavailable"
    assert ask("How about a packing list?", forecast)["answer_kind"] == "packing_list"
    climate = ask("What is the typical winter weather above Deurali?", forecast)
    assert "S03" in {c["fact_id"] for c in climate["evidence"]} and "live" not in climate
    both = ask("Weather at ABC tomorrow and what should I pack?")
    assert both["live"]["status"] == "unavailable" and "G02" in {
        c["fact_id"] for c in both["evidence"]
    }
    prep = ask("What about packing and physical preparation?")
    assert {"G02", "F03"} <= {c["fact_id"] for c in prep["evidence"]}


def test_explicit_origin_replaces_previous_origin(ask):
    root = ask("I have five walking days. Which ABC route would suit me?")
    selected = ask("How far is the Siwai route?", root)
    assert selected["variant_context"]["keys"] == ["siwai"]
    assert "combination of stops" not in selected["answer"]
    new_plan = ask("List the daily itinerary for this version.", selected)
    assert "Day 1 · Walk Siwai → Chhomrong" in new_plan["answer"]


def test_variant_time_after_topic_change(ask):
    root = ask("Compare ABC options for five walking days.")
    pick = ask("Let's go with the Ghandruk version.", root)
    stage = ask("Where will I be on day 3?", pick)
    pack = ask("What should I carry?", stage)
    answer = ask("How long is that stage?", pack)
    assert "Chhomrong → Dovan" in answer["answer"] and "5–6 hours" in answer["answer"]
    assert [r["publisher"] for r in answer["itinerary_sources"]] == ["Haven Holidays Nepal"]


def test_duration_comparison_does_not_print_every_stage(ask):
    result = ask("Could you compare how long the Ghandruk and Poon Hill options take?")
    assert "7 days from Pokhara" in result["answer"] and "8 days from Pokhara" in result["answer"]
    assert "Day 1 ·" not in result["answer"]


def test_packing_for_selected_plan_then_return_to_its_stages(ask):
    overview = ask("How far is the Annapurna Base Camp trek?")
    selected = ask("From Nayapul/Birethanti — 90–95 km", overview)
    plan = ask("can you manage a hiking plan for me in this case", selected)
    assert "Day 7 · Walk Jhinu Hot Spring → Nayapul" in plan["answer"]
    for question in ("what should I bring for this plan", "What should we carry on this itinerary?",
                     "Can you give me a packing checklist for this hiking plan?"):
        gear = ask(question, plan)
        assert gear["answer_kind"] == "packing_list"
        assert "headlamp" in gear["answer"].lower() and "Day 1 ·" not in gear["answer"]
        assert gear["variant_context"] == plan["variant_context"]
        ids = {c["fact_id"] for c in gear["evidence"]}
        assert {"G01", "G04", "G08"} <= ids and not ids.intersection({"G06", "G07"})
        assert "Ghandruk → Sinuwa" in ask("Show me day 2.", gear)["answer"]


def test_relative_walking_stage_and_directed_time_share_publisher(ask):
    start = ask("On the Ghandruk itinerary, which is our first walking stage?")
    second = ask("And the one after that?", start)
    assert second["variant_context"]["stage"] == 3 and "Dovan" in second["answer"]
    matched = ask("How long from Dovan to Deurali?", second)
    assert "4–5 hours" in matched["answer"] and matched["variant_context"]["stage"] == 4
    for query in ("How long from Deurali to Dovan?", "How long from Bamboo to Deurali?"):
        unknown = ask(query, second)
        assert "no checked measurement" in unknown["answer"]
        assert not unknown["evidence"] and "hours" not in unknown["answer"]


def test_walking_finish_does_not_supply_a_transfer_clock(ask):
    finish = ask("Where is the walking finish on the Nayapul loop?")
    reply = ask("How many hours for the ride back to Pokhara?", finish)
    assert "Nayapul → Pokhara" in reply["answer"] and "no verified total duration" in reply["answer"]
    assert reply["variant_context"]["keys"] == ["nayapul"] and not reply["evidence"]


def test_stage_gain_and_both_clocks_are_independent(ask):
    first = ask("How much did KeiTreks climb from Deurali to Annapurna Base Camp?")
    assert [c["fact_id"] for c in first["evidence"]] == ["KT-D4-ASC-APPROX"]
    assert "about 1,000 metres" in first["answer"] and "hours" not in first["answer"]
    moving = ask("How long were they actually on the move?", first)
    assert [c["fact_id"] for c in moving["evidence"]] == ["KT-D4-M"]
    assert "4 hours and 30 minutes" in moving["answer"]
    with_stops = ask("And from start to finish, including breaks?", moving)
    assert [c["fact_id"] for c in with_stops["evidence"]] == ["KT-D4-E"]
    assert "7 hours and 43 minutes" in with_stops["answer"]
    for parent, source in ((moving, "KT-D4-M"), (with_stops, "KT-D4-E")):
        check = ask("Does that include stops?", parent)
        assert [c["fact_id"] for c in check["evidence"]] == [source]
    assert "1,000 metres" in ask("And the total uphill, in metres?", with_stops)["answer"]
    reverse = ask("How much climbing was there going the other way?", first)
    assert not reverse["evidence"] and "Annapurna Base Camp to Deurali" in reverse["answer"]
    assert not ask("What was the moving time?", reverse)["evidence"]


def test_dont_substitute_day_or_other_publisher_for_explicit_stage(ask):
    clash = ask("On KeiTreks day three, how much ascent from Deurali to ABC?")
    assert not clash["evidence"] and "do not match" in clash["answer"]
    root = ask("Show me the Nayapul itinerary.")
    other = ask("How much ascent from Deurali to ABC?", root)
    assert "1,000" not in other["answer"] and other["variant_context"]["keys"] == ["nayapul"]


def test_explicit_return_endpoints_are_not_reversed_twice(ask):
    forward = ask("How many metres of climbing from Deurali via MBC to ABC?")
    assert [c["fact_id"] for c in forward["evidence"]] == ["KT-D4-ASC-APPROX"]
    back = ask("On the way back from ABC to Deurali, how much elevation did they gain?", forward)
    assert not back["evidence"] and "Annapurna Base Camp to Deurali" in back["answer"]
