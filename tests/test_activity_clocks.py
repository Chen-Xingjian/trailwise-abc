from app.activity_clocks import activity_answer
from app.turn_context import TrailFocus
from app.variant_plans import PlanContext, comparison_followup


def test_own_times_and_multiple_stops():
    result = activity_answer("I started at 09:00 and finished at 12:00 with a 10-minute break and a 20-minute lunch. Give both clocks.")
    assert result["personal_clock"] == (180, 150) and result["evidence"] == []
    reply = activity_answer("How much of my walk was moving again?", TrailFocus(personal_clock=(180, 150)))
    assert reply["personal_clock"] == (180, 150)


def test_conflicting_readings_and_appointment():
    assert "confirm" in activity_answer("My tracker: 4 hours moving, 3 hours elapsed.")["answer"]
    assert activity_answer("I arrive at the airport at 08:00 and finish at 15:00 after lunch.") is None


def test_comparison_preserves_active_version_but_allows_explicit_switch():
    selected = PlanContext(keys=["nayapul"], stage=1)
    saved = comparison_followup("Can I use Siwai GPS time for my final leg?", selected)
    assert saved["variant_context"]["keys"] == ["nayapul"] and selected.stage == 1
    assert saved["variant_context"]["stage"] == 7
    assert comparison_followup("Switch to Siwai and show the GPS times.", selected) is None
