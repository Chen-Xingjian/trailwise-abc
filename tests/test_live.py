from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.live import NEPAL, UNITS, WalkingWindow, explicit_forecast_window, forecast, notices
from app.main import create_app

NOW = datetime(2026, 11, 24, 14, tzinfo=UTC)
WINDOW = WalkingWindow(point="Deurali", day="2026-11-25", start="07:00", end="09:00")


def payload():
    return {
        "latitude": 28.5,
        "longitude": 83.875,
        "elevation": 3184,
        "utc_offset_seconds": 20700,
        "timezone": "Asia/Kathmandu",
        "hourly_units": UNITS,
        "hourly": {
            "time": [f"2026-11-25T{h:02}:45" for h in range(6, 10)],
            "temperature_2m": [-1, 0, 1, 2],
            "snowfall": [9, 0, 0.5, 0],
            "wind_gusts_10m": [99, 20, 19, 18],
            "precipitation": [0, 0, 1, 0],
        },
    }


def source(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_recent_run_nepal_window_and_boundaries():
    runs = []

    def respond(req):
        runs.append(req.url.params["run"])
        if len(runs) == 1:
            return httpx.Response(404)
        return httpx.Response(200, json=payload())

    with source(respond) as client:
        result = forecast(WINDOW, client, NOW)
    assert runs == ["2026-11-24T12:00", "2026-11-24T06:00"]
    assert result["status"] == "forecast" and result["trail_access"] == "unverified"
    assert result["hours"][0] == {"local_time": "2026-11-25T06:45", "temperature_2m": -1}
    assert "predicts snowfall" in result["message"] and result["grid_distance_km"] < 4
    assert result["run_initialised_utc"] != result["checked_at_utc"]


@pytest.mark.parametrize(
    "change", ["location", "altitude", "time_zone", "units", "gap", "missing", "past"]
)
def test_mismatched_and_expired_forecasts_are_not_used(change):
    data = payload()
    if change == "location":
        data["latitude"] = 27
    if change == "altitude":
        data["elevation"] = 800
    if change == "time_zone":
        data["utc_offset_seconds"] = 0
    if change == "units":
        data["hourly_units"] = {**UNITS, "snowfall": "inch"}
    if change == "gap":
        data["hourly"]["time"][1] = data["hourly"]["time"][0]
    if change == "missing":
        data["hourly"]["snowfall"][2] = None
    if change == "past":
        data["hourly"]["time"] = [s.replace("-25", "-23") for s in data["hourly"]["time"]]
    with source(lambda _: httpx.Response(200, json=data)) as client:
        result = forecast(WINDOW, client, NOW)
    assert result["status"] == "unavailable" and "hours" not in result


def test_out_of_horizon_skips_network_and_failure_does_not_invent_values():
    window = WINDOW.model_copy(update={"day": (NOW - timedelta(days=1)).date()})
    with source(lambda _: pytest.fail("Past walking window reached network")) as client:
        assert forecast(window, client, NOW)["status"] == "unavailable"
    with source(lambda _: httpx.Response(429)) as client:
        assert forecast(WINDOW, client, NOW)["status"] == "unavailable"


def test_notices_report_mentions_without_confirming_access():
    feed = """<rss><channel><lastBuildDate>Tue, 24 Nov 2026 10:00:00 GMT</lastBuildDate>
    <item><title>Manaslu reopened</title><link>https://trade.ntb.gov.np/m</link></item>
    <item><title>Bridge work</title><description>above Chhomrong</description>
    <link>https://trade.ntb.gov.np/a</link><pubDate>Tue, 24 Nov 2026 09:00:00 GMT</pubDate></item>
    </channel></rss>"""
    for body, count in ((feed, 1), (feed.replace("Chhomrong", "Pokhara"), 0)):
        with source(lambda _, body=body: httpx.Response(200, text=body)) as client:
            result = notices(client, NOW)
        assert result["status"] == "checked" and result["trail_access"] == "unverified"
        assert len(result["items"]) == count
    with source(lambda _: httpx.Response(200, text="<html/>")) as client:
        assert notices(client, NOW)["status"] == "unavailable"


def test_live_controls_and_question_entry(tmp_path):
    q = "Forecast for Deurali tomorrow from 07:00 to 09:00"
    assert explicit_forecast_window(q, NOW) == WINDOW
    assert (
        explicit_forecast_window("Will it snow at Deurali tomorrow between 7am and 9am?", NOW)
        == WINDOW
    )
    assert explicit_forecast_window("Weather for ABC tomorrow from 9pm to 8pm", NOW) is None
    assert explicit_forecast_window("Forecast for Deurali to MBC tomorrow morning", NOW) is None
    config = Settings(
        release_dir=ROOT / "data/release",
        runtime_dir=tmp_path,
        model_base_url="http://127.0.0.1:9/v1",
    )
    application = create_app(config)
    with TestClient(application) as app, source(lambda _: httpx.Response(503)) as offline:
        application.state.public_sources = offline
        assert b"forecast-form" not in app.get("/").content
        assert b"notice-check" not in app.get("/").content
        answer = app.post("/api/ask", json={"question": q, "offer_live_checks": True}).json()
        assert answer["answer_kind"] == "live_result" and answer["live"]["status"] == "unavailable"
        mixed = app.post(
            "/api/ask",
            json={
                "question": "Will it snow from Deurali to MBC tomorrow?",
                "offer_live_checks": True,
            },
        ).json()
        assert mixed["answer_kind"] == "live_clarification"
        base = app.post(
            "/api/ask", json={"question": q, "mode": "baseline", "offer_live_checks": True}
        ).json()
        assert base["answer_kind"] == "live_result" and base["mode"] == "baseline"
        assert base["live"] == answer["live"] and base["evidence"] == []
        closed_book = app.post("/api/ask", json={"question": q, "mode": "baseline"}).json()
        assert not closed_book["answer_kind"].startswith("live")
        tomorrow = (datetime.now(NEPAL) + timedelta(days=1)).date().isoformat()
        ws = {"point": "ABC", "day": tomorrow, "start": "09:00", "end": "12:00"}
        assert app.post("/api/live/forecast", json=ws).json()["status"] == "unavailable"
        assert app.post("/api/live/forecast", json={**ws, "point": "Pokhara"}).status_code == 422
        assert app.post("/api/live/forecast", json={**ws, "end": "08:00"}).status_code == 422
        assert app.post("/api/live/notices").json()["trail_access"] == "unverified"


def test_weather_dialogue_carries_only_needed_details_and_checks_both_tools():
    from app.live_chat import ChatContext, chat_lookup

    windows, notices_seen = [], []

    def wx(window):
        windows.append(window)
        return {"status": "unavailable", "message": "Forecast provider offline."}

    def road(section):
        notices_seen.append(section)
        return {"section": section, "message": "No current field observation."}

    def ask(q, previous=None):
        context = ChatContext.model_validate(previous["chat_context"]) if previous else None
        return chat_lookup(q, context, NOW, wx, road)

    first = ask("Will it snow on the Deurali to MBC trail tomorrow and is the trail open?")
    assert (
        first["answer_kind"] == "live_clarification"
        and first["live"]["section"] == "Deurali to MBC"
    )
    assert "which date" not in first["answer"]
    second = ask("Use Deurali, starting at 07:00.", first)
    assert second["answer"] == "Could you tell me your finish time in Nepal?"
    third = ask("09:00", second)
    assert windows == [WINDOW] and notices_seen == ["Deurali to MBC"]
    assert third["answer"] == "Forecast provider offline."
    fourth = ask("Is it open there now?", third)
    assert fourth["live"]["section"] == "Deurali to MBC" and notices_seen == ["Deurali to MBC"] * 2
    assert ask("What was the recorded moving time on day 3?", first) is None
    assert ask("Will it snow on Everest tomorrow?", first) is None
    mixed = ask("Weather and trail conditions at Deurali tomorrow, 7 to 9am?")
    assert mixed["live"]["status"] == "unavailable" and "notice_result" in mixed
    assert windows[-1] == WINDOW


@pytest.mark.parametrize(
    "problem", [None, "wrong_date", "missing_temperature", "wrong_unit", "wrong_grid"]
)
def test_tomorrow_weather_after_route_distance_uses_daily_point_forecast(tmp_path, problem):
    from app.live import DAILY_UNITS, POINTS

    day = (datetime.now(NEPAL).date() + timedelta(days=1)).isoformat()
    lat, lon, elevation = POINTS["ABC"]
    calls = []

    def respond(req):
        calls.append(req.url)
        assert req.url.path == "/v1/forecast"
        assert req.url.params["start_date"] == req.url.params["end_date"] == day
        assert float(req.url.params["elevation"]) == elevation
        daily = {
            "time": [day],
            "temperature_2m_min": [-3],
            "temperature_2m_max": [2],
            "precipitation_sum": [5],
            "snowfall_sum": [1],
            "wind_gusts_10m_max": [35],
        }
        data = {
            "latitude": lat,
            "longitude": lon,
            "elevation": elevation,
            "timezone": "Asia/Kathmandu",
            "utc_offset_seconds": 20700,
            "daily_units": dict(DAILY_UNITS),
            "daily": daily,
        }
        if problem == "wrong_date":
            daily["time"] = ["1999-01-01"]
        if problem == "missing_temperature":
            daily["temperature_2m_min"] = [None]
        if problem == "wrong_unit":
            data["daily_units"]["wind_gusts_10m_max"] = "mph"
        if problem == "wrong_grid":
            data["latitude"] += 5
        return httpx.Response(200, json=data)

    application = create_app(Settings(release_dir=ROOT / "data/release", runtime_dir=tmp_path))
    with TestClient(application) as app, source(respond) as provider:
        application.state.public_sources = provider
        response = app.post(
            "/api/ask",
            json={
                "question": "what is the weather when I go there tomorrow",
                "offer_live_checks": True,
                "trail_focus": {"route": "Annapurna Base Camp"},
            },
        )
        baseline = app.post("/api/ask", json={"question": "what is the weather there tmr?",
            "baseline_history": [{"question": "I am going to ABC", "answer": "OK"}],
            "mode": "baseline", "offer_live_checks": True}).json()
        assert baseline["live"] == response.json()["live"] and baseline["evidence"] == []
        assert "planning_evidence" not in baseline["live"]
    assert response.status_code == 200 and len(calls) == 1
    answer = response.json()
    assert answer["answer_kind"] == "live_result" and answer["live"]["period"] == "day"
    assert answer["live"]["point"] == "ABC" and answer["live"]["local_date"] == day
    if problem:
        assert "unavailable" in answer["answer"] and "daily" not in answer["live"]
    else:
        assert "-3 to 2 °C" in answer["answer"] and "35 km/h" in answer["answer"]


def test_weather_invalid_explicit_window_never_silently_becomes_daily():
    from app.live_chat import chat_lookup

    def no_call(*args):
        pytest.fail("Invalid walking window reached the provider")

    answer = chat_lookup("Forecast at ABC tomorrow from 9pm to 8pm", None, NOW, no_call, no_call)
    assert (
        answer["answer_kind"] == "live_clarification"
        and "finish after the start" in answer["answer"]
    )
