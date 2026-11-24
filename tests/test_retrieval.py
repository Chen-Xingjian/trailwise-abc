import pytest

from app.config import ROOT, Settings
from app.release import load_release
from app.retrieval import Retriever, trip_budget_question


def test_same_count_modified_payload_is_rejected(tmp_path):
    release = load_release(ROOT / "data/release")
    settings = Settings(runtime_dir=tmp_path)
    retriever = Retriever(release, settings)
    point_id = next(iter(retriever._chunks_by_point))
    retriever.client.set_payload(
        retriever.collection, payload={"text": "Unreviewed replacement"}, points=[point_id]
    )
    retriever.close()
    with pytest.raises(ValueError, match="payload differs"):
        Retriever(release, settings)


def test_reopen_verified_payload_and_reference_filter(tmp_path):
    release = load_release(ROOT / "data/release")
    settings = Settings(runtime_dir=tmp_path)
    first = Retriever(release, settings)
    first.close()
    second = Retriever(release, settings)
    hits = second.search("walking stages Siwai", reference_id="ABC-KT-06")
    assert hits and {h["fact_id"] for h in hits} <= {"K07", "K08"}
    assert all(h["source_records"] for h in hits)
    second.close()


@pytest.mark.parametrize(("question", "expected"), [
    ("Can we fit the whole trek into eight days including transfers?", True),
    ("With travel included, how would you plan a Monday to Friday itinerary?", True),
    ("What was the full door-to-door time for day five?", False),
    ("How much ascent did the full route have?", False),
])
def test_trip_budget_is_distinct_from_stage_timing(question, expected):
    assert trip_budget_question(question) is expected


def test_natural_place_names_find_the_reviewed_sequence(tmp_path):
    release = load_release(ROOT / "documents/abc-six-day")
    retriever = Retriever(release, Settings(runtime_dir=tmp_path))
    try:
        examples = {
            "Where do I stop each day on the six-day Annapurna Base Camp trek from Siwai?": "K08",
            "Which places do I pass between Dobhan and Machhapuchhare Base Camp?": "W03",
            "Which villages do I pass when I start the Annapurna Sanctuary trek from Nayapul?": "W01",
        }
        for question, expected in examples.items():
            assert [hit["fact_id"] for hit in retriever.search(question)] == [expected]
        assert retriever._named_sequence("Which villages do I pass from Nayapul to Pokhara?", None) is None
        assert retriever._named_sequence("Which villages do I pass from Nayapul?", "ABC-KT-06") is None
    finally:
        retriever.close()
