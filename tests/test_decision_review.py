from app.config import ROOT
from app.document_review import material_answer
from app.live_chat import ChatContext
from app.planning import personal_walking_days
from app.preparation import reviewed_guidance
from app.release import load_release
from app.turn_context import TrailFocus

RELEASE = load_release(ROOT / "documents/abc-six-day")


def test_walk_allocation_must_be_confirmed():
    assert personal_walking_days("Three complete days remain for walking.") == 3
    assert (
        personal_walking_days("Three full days are left for walking, and our dates are fixed.") == 3
    )
    for text in [
        "Maybe three days remain for hiking.",
        "Do five days remain for hiking?",
        "I have four days including transfers.",
        "A brochure lists six walking days.",
    ]:
        assert personal_walking_days(text) is None


def test_reverse_stage_never_borrows_forward_observations():
    answer = reviewed_guidance(
        "My practice was downhill. Am I ready for the KeiTreks climb from Bamboo to ABC?",
        RELEASE,
        "ABC-KT-06",
    )
    assert [c["fact_id"] for c in answer["evidence"]] == ["F03"]
    assert "2,000" not in answer["answer"] and "8 hours" not in answer["answer"]


def test_grid_readout_uses_sites_own_signed_elevation():
    for place, month, expected, direction in [
        ("ABC", "April", "S05-ABC-04", "125 m above"),
        ("Deurali", "February", "S05-DEURALI-02", "189 m below"),
        ("Chhomrong", "November", "S05-CHHOMRONG-11", "540 m above"),
    ]:
        answer = material_answer(
            f"What does the historical climate grid show at {place} in {month}?",
            RELEASE,
            TrailFocus(),
            None,
        )
        assert [c["fact_id"] for c in answer["evidence"]] == [expected]
        assert direction in answer["answer"]


def test_saved_forecast_can_be_followed_by_a_new_lookup():
    prev = ChatContext(reviewing_forecast=True)
    for text in [
        "Get the latest forecast for Deurali tomorrow.",
        "What should I pack?",
        "How cold will it be tomorrow?",
    ]:
        assert material_answer(text, RELEASE, TrailFocus(), prev) is None
    response = material_answer(
        "My screenshot is for ABC. I will walk at Annapurna Base Camp. Can I use it?",
        RELEASE,
        TrailFocus(),
        prev,
    )
    assert "different point" not in response["answer"] and "S06" in response["verification_rules"]
