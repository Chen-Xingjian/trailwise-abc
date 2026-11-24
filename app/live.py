"""Read-only, on-demand sources for the ABC corridor. No writes to the reviewed corpus."""

import math
import re
from datetime import UTC, date, datetime, time, timedelta
from email.utils import parsedate_to_datetime
from typing import Literal
from urllib.parse import urlsplit
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict, model_validator

NEPAL = ZoneInfo("Asia/Kathmandu")
FORECAST = "https://single-runs-api.open-meteo.com/v1/forecast"
DAILY_FORECAST = "https://api.open-meteo.com/v1/forecast"
BULLETINS = "https://trade.ntb.gov.np/category/situation-updates/feed/"
# KeiTreks end-of-stage track points in the accepted S05 site audit (D1, D3, D4).
POINTS = {
    "Chhomrong": (28.4175924, 83.8187085, 2209),
    "Deurali": (28.500371, 83.9004043, 3184),
    "ABC": (28.5309351, 83.8808964, 4090),
}
UNITS = {"temperature_2m": "°C", "precipitation": "mm", "snowfall": "cm", "wind_gusts_10m": "km/h"}
CORRIDOR = re.compile(
    r"\b(annapurna (?:base camp|sanctuary)|chh?omr?ong|sinuwa|deurali|jhinu|machh?apuchh?(?:are|re)|siwai)\b",
    re.I,
)
MAX_RUN_AGE = timedelta(hours=18)


class ForecastDay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    point: Literal["Chhomrong", "Deurali", "ABC"]
    day: date


class WalkingWindow(ForecastDay):
    start: time
    end: time

    @model_validator(mode="after")
    def validate_window(self):
        if any(t.tzinfo or t.second or t.microsecond for t in (self.start, self.end)):
            raise ValueError("Enter Nepal local hours and minutes.")
        if self.end <= self.start:
            raise ValueError("End time must follow start time on the same Nepal date.")
        return self


def grid_distance(data, point):
    lat, lon, altitude = POINTS[point]
    # Single Runs returns a model grid centre; elevation is the downscaling target.
    grid_lat, grid_lon = float(data["latitude"]), float(data["longitude"])
    if not (-90 <= grid_lat <= 90 and -180 <= grid_lon <= 180):
        raise ValueError("Invalid forecast coordinates.")
    delta = (
        math.sin(math.radians(grid_lat - lat) / 2) ** 2
        + math.cos(math.radians(lat))
        * math.cos(math.radians(grid_lat))
        * math.sin(math.radians(grid_lon - lon) / 2) ** 2
    )
    distance = 12742 * math.asin(math.sqrt(delta))
    if not (distance <= 15 and abs(float(data["elevation"]) - altitude) <= 1):
        raise ValueError("Forecast grid or target elevation does not match the requested point.")
    if data["utc_offset_seconds"] != 20700 or data["timezone"] != "Asia/Kathmandu":
        raise ValueError("Invalid forecast time zone.")
    return round(distance, 1)


def read_forecast(data, window, run):
    distance = grid_distance(data, window.point)
    if not isinstance(data["hourly_units"], dict) or any(
        data["hourly_units"].get(k) != v for k, v in UNITS.items()
    ):
        raise ValueError("Unexpected forecast units.")
    h = data["hourly"]
    stamps = [datetime.fromisoformat(t) for t in h["time"]]
    if any(t.tzinfo is not None for t in stamps) or any(len(h[k]) != len(stamps) for k in UNITS):
        raise ValueError("Inconsistent hourly forecast.")
    begin = datetime.combine(window.day, window.start)
    end = datetime.combine(window.day, window.end)
    # Use complete model hours bracketing the walk, including the preceding-hour
    # interval ending just after the finish. Never present a prorated accumulation.
    before = [i for i, t in enumerate(stamps) if t <= begin]
    after = [i for i, t in enumerate(stamps) if t >= end]
    if not before or not after:
        return None
    left, right = before[-1], after[0]
    if len(set(stamps)) != len(stamps) or stamps != sorted(stamps):
        return None
    if left >= right or any(
        stamps[i] - stamps[i - 1] != timedelta(hours=1) for i in range(left + 1, right + 1)
    ):
        return None
    rows = []
    for i in range(left, right + 1):
        row = {"local_time": stamps[i].isoformat(timespec="minutes")}
        for k in UNITS:
            if i == left and k != "temperature_2m":
                continue  # that accumulation/maximum refers to the hour before the window
            v = h[k][i]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                return None
            if k != "temperature_2m" and v < 0:
                return None
            row[k] = v
        rows.append(row)
    return {
        "hours": rows,
        "grid_distance_km": round(distance, 1),
        "grid_coordinates": [data["latitude"], data["longitude"]],
        "target_elevation_m": POINTS[window.point][2],
        "run_initialised_utc": run.isoformat(),
        "units": UNITS,
    }


DAILY_UNITS = {
    "temperature_2m_min": "°C",
    "temperature_2m_max": "°C",
    "precipitation_sum": "mm",
    "snowfall_sum": "cm",
    "wind_gusts_10m_max": "km/h",
}


def daily_forecast(request, client, now):
    day = request.day.isoformat()
    lat, lon, elevation = POINTS[request.point]
    base = {
        "period": "day",
        "point": request.point,
        "local_date": day,
        "timezone": "Asia/Kathmandu",
        "model": "DWD ICON Global via Open-Meteo",
        "source": DAILY_FORECAST,
        "target_elevation_m": elevation,
        "checked_at_utc": now.isoformat(),
        "trail_access": "unverified",
    }
    today = now.astimezone(NEPAL).date()
    if not today <= request.day <= today + timedelta(days=3):
        return {
            **base,
            "status": "unavailable",
            "message": "Choose today or one of the next three dates in Nepal.",
        }
    params = dict(
        latitude=lat,
        longitude=lon,
        elevation=elevation,
        models="icon_global",
        timezone="Asia/Kathmandu",
        start_date=day,
        end_date=day,
        daily=",".join(DAILY_UNITS),
    )
    try:
        response = client.get(DAILY_FORECAST, params=params)
        response.raise_for_status()
        data = response.json()
        distance = grid_distance(data, request.point)
        if data["daily"]["time"] != [day]:
            raise ValueError("Wrong local date")
        values = {}
        for field, unit in DAILY_UNITS.items():
            (value,) = data["daily"][field]
            if (
                data["daily_units"][field] != unit
                or type(value) not in (int, float)
                or not math.isfinite(value)
                or ("temperature" not in field and value < 0)
            ):
                raise ValueError("Invalid daily value or unit")
            values[field] = value
        if values["temperature_2m_min"] > values["temperature_2m_max"]:
            raise ValueError("Inverted temperature range")
        return {
            **base,
            "status": "forecast",
            "source": str(response.request.url),
            "grid_distance_km": distance,
            "daily": values,
            "units": DAILY_UNITS,
        }
    except (httpx.HTTPError, ValueError, KeyError, TypeError, OverflowError):
        place = "Annapurna Base Camp" if request.point == "ABC" else request.point
        return {
            **base,
            "status": "unavailable",
            "message": f"The daily forecast for {place} on {day} is currently unavailable.",
        }


def forecast(window, client, now):
    current = now.astimezone(NEPAL)
    start = datetime.combine(window.day, window.start, NEPAL)
    base = {
        "point": window.point,
        "requested_start": start.isoformat(),
        "requested_end": datetime.combine(window.day, window.end, NEPAL).isoformat(),
        "source": FORECAST,
        "model": "DWD ICON Global via Open-Meteo",
        "checked_at_utc": now.isoformat(),
        "trail_access": "unverified",
    }

    def unavailable(reason):
        return {**base, "status": "unavailable", "message": reason}

    if start <= current or window.day > current.date() + timedelta(days=3):
        return unavailable(
            "Choose a future walking window within the next three Nepal calendar days."
        )
    now_utc = now.astimezone(UTC)
    run = now_utc.replace(hour=(now_utc.hour // 6) * 6, minute=0, second=0, microsecond=0)
    lat, lon, altitude = POINTS[window.point]
    while now_utc - run <= MAX_RUN_AGE:
        params = dict(
            latitude=lat,
            longitude=lon,
            elevation=altitude,
            models="icon_global",
            timezone="Asia/Kathmandu",
            hourly=",".join(UNITS),
            forecast_days=5,
            run=run.strftime("%Y-%m-%dT%H:%M"),
        )
        try:
            response = client.get(FORECAST, params=params)
            if response.status_code in (400, 404):
                run -= timedelta(hours=6)
                continue
            response.raise_for_status()
            result = read_forecast(response.json(), window, run)
            if result:
                snow = any(r.get("snowfall", 0) > 0 for r in result["hours"])
                message = (
                    "This run predicts snowfall in at least one hourly interval overlapping your walk."
                    if snow
                    else "This run predicts no snowfall in the hourly intervals overlapping your walk."
                )
                return {
                    **base,
                    **result,
                    "status": "forecast",
                    "source": str(response.request.url),
                    "message": message
                    + " Existing snow or ice on the path still requires a recent local report.",
                }
        except (httpx.HTTPError, ValueError, KeyError, TypeError, OverflowError):
            return unavailable(
                "The weather source could not supply a verified forecast for this point and window."
            )
        run -= timedelta(hours=6)
    return unavailable(
        "No complete hourly forecast from a run within the last 18 hours was available."
    )


def notice_date(text):
    try:
        stamp = parsedate_to_datetime(text or "")
        return stamp.astimezone(UTC).isoformat() if stamp.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def notices(client, now):
    base = {
        "publisher": "Nepal Tourism Board",
        "source": BULLETINS,
        "checked_at_utc": now.isoformat(),
        "trail_access": "unverified",
        "items": [],
    }
    try:
        response = client.get(BULLETINS)
        response.raise_for_status()
        channel = ElementTree.fromstring(response.content).find("channel")
        if channel is None or not channel.findall("item"):
            raise ValueError("Unrecognised or empty bulletin feed.")
        items = []
        for item in channel.findall("item"):
            title = item.findtext("title") or ""
            url = item.findtext("link") or ""
            parts = urlsplit(url)
            if parts.scheme != "https" or parts.netloc != "trade.ntb.gov.np":
                continue
            if CORRIDOR.search(title + " " + (item.findtext("description") or "")):
                items.append(
                    {
                        "title": title,
                        "url": url,
                        "published_utc": notice_date(item.findtext("pubDate")),
                    }
                )
        return {
            **base,
            "status": "checked",
            "items": items,
            "feed_updated_utc": notice_date(channel.findtext("lastBuildDate")),
            "message": (
                "These notices mention a corridor location. Verify the exact section, affected users and validity with the issuer."
                if items
                else "No corridor match in the current feed entries. Pedestrian access remains unverified."
            ),
        }
    except (httpx.HTTPError, ElementTree.ParseError, ValueError):
        return {
            **base,
            "status": "unavailable",
            "message": "The NTB bulletin feed could not be verified. Check the issuer or the local ACAP office.",
        }


DYNAMIC_DATE = re.compile(
    r"\b(today|tonight|tomorrow|tmr|tmrw|currently|current|latest|this week|next week|now|\d{4}-\d{2}-\d{2})\b",
    re.I,
)


def live_intent(question):
    """Recognise requests for current sources while keeping climate/history questions local."""
    if re.search(r"\b(everest|ebc|gokyo|manaslu|annapurna circuit|ama dablam)\b", question, re.I):
        return None
    dated = DYNAMIC_DATE.search(question)
    if not dated and re.search(
        r"\b(historical|typically|typical|average|seasonal|usually|climate|recorded|winter|monsoon)\b", question, re.I
    ):
        return None
    access = re.search(
        r"\b(open|closed|closur(?:e|es)|passable|impassable|blocked|roadblocks?|landslides?|washed out|bulletins?|notices?|crossable)\b|"
        r"\b(?:road|trail|path|bridge|route) (?:conditions?|status|updates?)\b|"
        r"\b(?:updates?|news) (?:on|about|for) (?:the )?(?:trail|road|bridge|path)\b",
        question,
        re.I,
    )
    weather = re.search(
        r"\b(weather|forecast|will it (?:rain|snow)|how (?:cold|windy) will it be)\b",
        question,
        re.I,
    )
    if dated and not weather:
        weather = re.search(
            r"\b(snow(?:fall|ing)?|ice|icy|rain(?:fall|ing)?|wind|temperature|traction)\b",
            question,
            re.I,
        )
    if weather and access:
        return "both"
    if access:
        return "notices"
    return "forecast" if weather else None


def explicit_forecast_window(question, now):
    # Parse only an unambiguous single-point, single-day request. The conversation handles
    # other phrasings without assigning an arbitrary point to an entire stage.
    clock = r"(\d{1,2}(?::\d{2}\s*(?:am|pm)?|\s*(?:am|pm)))"
    match = re.fullmatch(
        r"(?:what(?:'s| is) (?:the )?|check (?:the )?|show (?:me )?(?:the )?)?"
        r"(?:weather(?: forecast)?|forecast|will it (?:rain|snow)|how (?:windy|cold) will it be) "
        r"(?:at|for|in) (chhomrong|deurali|abc|annapurna base camp) "
        r"(?:on )?(today|tomorrow|\d{4}-\d{2}-\d{2}) "
        rf"(?:from |between )?{clock}\s*(?:to|until|and|[-–])\s*{clock}(?: nepal time)?[?.!]?",
        question.strip(),
        re.I,
    )
    if not match:
        return None
    point, day, first, last = match.groups()
    today = now.astimezone(NEPAL).date()

    def parse_clock(value):
        value = value.strip().lower().replace(" ", "")
        if value.endswith(("am", "pm")):
            return datetime.strptime(value, "%I:%M%p" if ":" in value else "%I%p").time()
        return time.fromisoformat(value.zfill(5))

    try:
        if day.lower() in ("today", "tomorrow"):
            walk_day = today + timedelta(days=int(day.lower() == "tomorrow"))
        else:
            walk_day = date.fromisoformat(day)
        label = {"abc": "ABC", "annapurna base camp": "ABC"}.get(point.lower(), point.title())
        return WalkingWindow(
            point=label,
            day=walk_day,
            start=parse_clock(first),
            end=parse_clock(last),
        )
    except ValueError:
        return None


def weather_answer(data):
    if data["status"] != "forecast":
        return data["message"]
    if data.get("period") == "day":
        d = data["daily"]
        place = "Annapurna Base Camp" if data["point"] == "ABC" else data["point"]
        return (
            f"At {place} ({data['target_elevation_m']:,} m) on {data['local_date']} Nepal time, "
            f"the forecast is {d['temperature_2m_min']:g} to {d['temperature_2m_max']:g} °C. "
            f"Total precipitation: {d['precipitation_sum']:g} mm. Forecast snowfall: {d['snowfall_sum']:g} cm. "
            f"Gusts may reach {d['wind_gusts_10m_max']:g} km/h."
        )
    temps = [r["temperature_2m"] for r in data["hours"]]
    gust = max(r["wind_gusts_10m"] for r in data["hours"][1:])
    return (
        f"For {data['point']} ({data['target_elevation_m']} m), the forecast samples around your walk "
        f"range from {min(temps):g} to {max(temps):g} °C, with gusts up to {gust:g} km/h. "
        f"Your walking window is {data['requested_start'].replace('T', ' ')} to {data['requested_end'][11:16]} Nepal time. "
        f"{data['message']} Trail access remains unverified."
        + (
            " For the section above Deurali, consider footwear traction if recent local reports "
            "indicate snow or ice there [G07]."
            if data.get("planning_evidence")
            else ""
        )
    )
