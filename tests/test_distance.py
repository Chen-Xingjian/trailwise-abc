import httpx
from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.distance import GUIDE, distance_question
from app.main import create_app


def test_chat_distinguishes_guide_estimates_from_reviewed_distance(tmp_path):
    settings = Settings(release_dir=ROOT / "documents/abc-six-day", runtime_dir=tmp_path)
    page = (
        "<h3>Siwai to Annapurna Base Camp Distance</h3>"
        "<p><b>Approximate round-trip walking distance: 65–70 km</b></p>"
        "<h3>Jhinu Danda to Annapurna Base Camp Distance</h3>"
        "<p>New layout without a verified number</p><p>80–90 km</p>"
    )
    app = create_app(settings)
    with (
        TestClient(app) as client,
        httpx.Client(
            transport=httpx.MockTransport(
                lambda req: (
                    httpx.Response(200, text=page) if str(req.url) == GUIDE else httpx.Response(404)
                )
            )
        ) as guide,
    ):
        app.state.public_sources = guide
        request = {"question": "What is the exact total distance of ABC-KT-06?"}
        for connected in (True, False):
            result = client.post(
                "/api/ask", json={**request, "offer_live_checks": connected}
            ).json()
            assert result["answer_kind"] == "route_distance"
            assert "unverified" in result["answer"] and "KT-D" not in result["answer"]
            assert ("65–70 km" in result["answer"]) is connected
            assert result["distance_guide"]["used"] is connected
            assert [e["fact_id"] for e in result["evidence"]] == ([] if connected else ["K07"])
            assert "80–90" not in result["answer"]
        result = client.post(
            "/api/ask",
            json={
                "question": "How far is the ABC trek from Jhinu Danda?",
                "offer_live_checks": True,
            },
        ).json()
        assert not result["distance_guide"]["used"] and "65–70" not in result["answer"]


def test_whole_trek_distance_scope():
    for question in [
        "How far is the ABC trek?",
        "How many kilometres is the Annapurna Base Camp trek?",
        "What is the exact total distance of ABC-KT-06?",
    ]:
        assert distance_question(question, None)
    for question in [
        "How far is Bamboo from ABC?",
        "How far is ABC one way?",
        "What is the distance to ABC by jeep?",
        "How far is EBC?",
        "What is the distance to ABC and how should I train?",
    ]:
        assert not distance_question(question, None)
    assert not distance_question("How far is ABC?", "ABC-WV-CORRIDOR")


def test_overview_and_contextual_trailhead_comparison(tmp_path):
    rows = [
        ("Starting point", "Approx. walking distance to ABC and back"),
        ("Jhinu Danda", "About 60–65 km"),
        ("Siwai/Jhinu area", "About 65–70 km"),
        ("Ghandruk", "About 70–80 km"),
        ("Nayapul/Birethanti area", "About 90–95 km"),
        ("Ghorepani + Poon Hill + ABC", "Usually 100+ km"),
    ]
    page = "<table>" + "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in rows) + "</table>"
    settings = Settings(release_dir=ROOT / "documents/abc-six-day", runtime_dir=tmp_path)
    app = create_app(settings)
    with (
        TestClient(app) as client,
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page))
        ) as guide,
    ):
        app.state.public_sources = guide

        def ask(question, **extra):
            answer = client.post(
                "/api/ask", json={"question": question, "offer_live_checks": True, **extra}
            ).json()
            assert answer["answer_kind"] == "route_distance"
            return answer

        first = ask("How far is the Annapurna Base Camp trek?")
        assert first["answer"].count(" km**") == 5 and "six-day" not in first["answer"]
        branch = {"distance_followup": True, "trail_focus": first["trail_focus"]}
        rendered_rows = [line for line in first["answer"].splitlines() if line.startswith("- ")]
        for row, key in zip(rendered_rows, ("jhinu", "siwai", "ghandruk", "nayapul", "poon"), strict=True):
            for message in (row, row.removeprefix("- ").replace("**", "")):
                selected = ask(message, **branch)
                assert selected["variant_context"]["keys"] == [key]
                assert row.split("**")[1] in selected["answer"]
                assert selected["distance_guide"]["used"] and selected["itinerary_sources"][0]["locator"]
        selected = ask("From Nayapul/Birethanti — 999–9999 km", **branch)
        assert "999" not in selected["answer"] and "90–95 km" in selected["answer"]
        assert "Birethanti itself" in selected["answer"]
        next_day = client.post("/api/ask", json={
            "question": "Show me day 2.", "distance_followup": True,
            "trail_focus": selected["trail_focus"], "variant_context": selected["variant_context"],
        }).json()
        assert next_day["variant_context"]["keys"] == ["nayapul"] and "Day 2 ·" in next_day["answer"]
        unavailable = client.post("/api/ask", json={
            "question": "From Nayapul/Birethanti — 90–95 km", **branch, "offer_live_checks": False,
        }).json()
        assert not unavailable["distance_guide"]["used"] and "90–95" not in unavailable["answer"]
        assert unavailable["itinerary_sources"] and "7 days from Pokhara" in unavailable["answer"]
        for question, expected in [
            ("Ghandruk", "70–80"),
            ("How about Birethanti?", "90–95"),
            ("What if I go via Poon Hill?", "100+"),
            ("From Siwai", "65–70"),
        ]:
            answer = ask(question, **branch)["answer"]
            assert expected in answer and answer.count(" km**") == 1 and "six-day" not in answer
        custom = ask("How far is ABC from Nayapul via Poon Hill and finishing at Jhinu Danda?")[
            "answer"
        ]
        assert "particular combination" in custom and "90–95" not in custom
        assert "100+" not in ask("How far is ABC without Poon Hill?")["answer"]
        assert "100+" not in ask("How far is the six-day ABC trek from Siwai?")["answer"]


def test_complete_table_cache_never_serves_expired_or_offline_values(monkeypatch):
    from app import distance

    cache = distance.DistanceGuideCache()
    cache.ranges = {"Siwai": "65–70 km"}
    cache.fetched_at = "2026-11-24T10:00:00+00:00"
    cache.expires = 100
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as client:
        monkeypatch.setattr(distance.time, "monotonic", lambda: 90)
        assert cache.read(client) == (cache.ranges, cache.fetched_at)
        assert cache.read(None) == ({}, None)
        monkeypatch.setattr(distance.time, "monotonic", lambda: 101)
        assert cache.read(client) == ({}, None)
