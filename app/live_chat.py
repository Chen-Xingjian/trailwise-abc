"""Carry public ABC lookup parameters between turns in one browser conversation."""

import re
from datetime import date, datetime, time, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.live import NEPAL, ForecastDay, WalkingWindow, live_intent, weather_answer
from app.preparation import TRAINING_REQUEST
from app.trail_updates import Section, question_section

Tool = Literal["forecast", "notices", "both"]
Point = Literal["Deurali", "Chhomrong", "ABC"]
PLACES = re.compile(
    r"\b(deurali|chhomrong|abc|annapurna base camp|mbc|machhapuchhare base camp|bamboo|siwai|pokhara|jhinu danda|ghandruk|poon hill|ghorepani|birethanti|nayapul|tadapani|dovan|sinuwa|ulleri)\b",
    re.I,
)
CLOCK = r"(?:\d{1,2}:\d{2}\s*(?:am|pm)?|\d{1,2}\s*(?:am|pm))"
HOURS = re.compile(rf"(?<![\w:])({CLOCK})\s*(?:to|until|through|and|[-–])\s*({CLOCK})\b", re.I)
DATES = re.compile(r"\b(day after tomorrow|today|tomorrow|tmr|tmrw|tonight|\d{4}-\d{2}-\d{2})\b", re.I)


class ChatContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: Tool | None = None
    point: Point | None = None
    section: Section = "ABC corridor"
    day: date | None = None
    start: time | None = None
    end: time | None = None
    awaiting: bool = False
    reviewing_forecast: bool = False
    climate_fact: str | None = Field(None, pattern=r"^S05-(ABC|CHHOMRONG|DEURALI)-(0[1-9]|1[0-2])$")

    @field_validator("start", "end")
    @classmethod
    def local_minute(cls, value):
        if value and (value.tzinfo or value.second or value.microsecond):
            raise ValueError("Use local hours and minutes.")
        return value


def clock_value(value):
    value = value.lower().replace(" ", "")
    if value.endswith(("am", "pm")):
        return datetime.strptime(value, "%I:%M%p" if ":" in value else "%I%p").time()
    return time.fromisoformat(value.zfill(5))


def read_slots(text, ctx, now):
    places = {p.lower() for p in PLACES.findall(text)}
    if places:
        points = {
            "deurali": "Deurali",
            "chhomrong": "Chhomrong",
            "annapurna base camp": "ABC",
            "abc": "ABC",
        }
        mapped = {points.get(p) for p in places}
        ctx.point = mapped.pop() if len(mapped) == 1 else None
        section = question_section(text)
        if section != "ABC corridor" or not ctx.awaiting:
            ctx.section = section
    days = DATES.findall(text)
    try:
        if days:
            relative = {"today": 0, "tonight": 0, "tomorrow": 1, "tmr": 1, "tmrw": 1, "day after tomorrow": 2}
            value = days[-1].lower()
            ctx.day = (
                (
                    now.astimezone(NEPAL).date() + timedelta(days=relative[value])
                    if value in relative
                    else date.fromisoformat(value)
                )
                if len(days) == 1
                else None
            )
        elif re.search(
            r"\b(next|this) (?:week|weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            text,
            re.I,
        ):
            ctx.day = None
    except ValueError:
        ctx.day = None
    span = HOURS.search(text)
    shared_period = re.search(r"\b(\d{1,2})\s*(?:to|and|[-–])\s*(\d{1,2})\s*(am|pm)\b", text, re.I)
    if shared_period and not span:
        first, last, period = shared_period.groups()
        if 1 <= int(first) < int(last) <= 11:
            span = HOURS.search(first + period + " to " + last + period)
    try:
        if span:
            ctx.start, ctx.end = (clock_value(value) for value in span.groups())
        else:
            for field, prefix in [
                ("start", r"from|start(?:ing)?(?: at)?"),
                ("end", r"until|finish(?:ing)?(?: at)?|end(?:ing)?(?: at)?"),
            ]:
                one = re.search(rf"\b(?:{prefix})\s+({CLOCK})\b", text, re.I)
                if one:
                    setattr(ctx, field, clock_value(one[1]))
            bare = re.fullmatch(rf"\s*({CLOCK})[.!]?\s*", text, re.I)
            if bare and ctx.awaiting and bool(ctx.start) != bool(ctx.end):
                setattr(ctx, "end" if ctx.start else "start", clock_value(bare[1]))
    except ValueError:
        ctx.start = ctx.end = None
    if ctx.start and ctx.end and (ctx.end <= ctx.start or ctx.start.tzinfo or ctx.end.tzinfo):
        ctx.start = ctx.end = None
    return ctx


def chat_lookup(question, previous, now, point_forecast, trail_notices):
    text = question.strip()
    if re.search(r"\b(everest|ebc|gokyo|manaslu|annapurna circuit|ama dablam)\b", text, re.I):
        return None
    intent = live_intent(text)
    fragment = bool(
        re.search(
            r"^(?:what about|how about|actually|instead|same|there|at |from |until |tomorrow|today|use |\d)",
            text,
            re.I,
        )
        or (PLACES.search(text) and len(text.split()) <= 6)
        or HOURS.search(text)
        or DATES.search(text)
        or re.fullmatch(r"(?:morning|afternoon|evening|same time)[.!]?", text, re.I)
    )
    unrelated = TRAINING_REQUEST.search(text) or re.search(
        r"\b(historical|training|sleeping bag|recorded|moving time|fitness|walking days|practice|seasonal average|"
        r"pack(?:ing)?|checklist|bring|train|winter|monsoon|typically|climate|poles?|equipment|gear|shoes|altitude|ascent|descent|distance|bedding|food|water)\b",
        text,
        re.I,
    )
    if (
        previous
        and previous.awaiting
        and not intent
        and not unrelated
        and len(text.split()) <= 4
        and "?" not in text
    ):
        fragment = True
    if not intent and (not previous or not previous.tool or not fragment or unrelated):
        return None
    follow = previous and (
        (previous.awaiting and not unrelated)
        or fragment
        or (intent and not PLACES.search(text))
        or re.search(r"\b(there|same|that (?:section|day|place|point)|it like)\b", text, re.I)
    )
    if (
        previous
        and previous.awaiting
        and re.search(
            r"\b(?:don.t know|not sure|can.t confirm|cannot confirm|undecided)\b", text, re.I
        )
        and not intent
    ):
        return {
            "mode": "rag",
            "answer_kind": "live_result",
            "evidence": [],
            "warnings": [],
            "answer": "The forecast will be more useful once you know where and when you will walk. You can still ask for current trail notices now.",
            "chat_context": previous.model_copy(update={"awaiting": False}).model_dump(mode="json"),
        }
    ctx = previous.model_copy() if follow else ChatContext()
    tool = intent or previous.tool
    ctx.tool = tool
    # A new general forecast request gets the day back, even after an earlier
    # hourly request. Explicit references to the same window retain its hours.
    if (
        intent in {"both", "forecast"}
        and not re.search(CLOCK, text, re.I)
        and not re.search(
            r"\b(same (?:time|hours|window)|during (?:my|our|the) (?:walk|hike))\b", text, re.I
        )
    ):
        ctx.start = ctx.end = None
    read_slots(text, ctx, now)
    answer = {"mode": "rag", "answer_kind": "live_result", "warnings": [], "evidence": []}
    parts = []
    if tool in ("both", "notices"):
        notice = trail_notices(ctx.section)
        answer["live"] = notice
        message = notice["message"]
        entries = notice.get("items", [])[:2]
        if entries:
            message += " Listed notices: " + ", ".join(item["title"] for item in entries) + "."
        if "pedestrian access remains unverified" not in message.lower():
            message += " Pedestrian access remains unverified."
        parts.append(f"{ctx.section}: {message}")
    if tool in ("both", "forecast"):
        missing = []
        if not ctx.point:
            missing.append(
                "which forecast point to use (Chhomrong, Deurali or Annapurna Base Camp)"
            )
        if not ctx.day:
            missing.append("which date you plan to walk")
        if ctx.end and not ctx.start:
            missing.append("your start time in Nepal")
        elif ctx.start and not ctx.end:
            missing.append("your finish time in Nepal")
        elif not ctx.start and re.search(CLOCK, text, re.I):
            missing.append(
                "a valid start and finish time in Nepal, with the finish after the start"
            )
        if missing:
            ctx.tool = "forecast"  # Any requested bulletin has already been returned.
            ctx.awaiting = True
            answer["answer_kind"] = "live_clarification"
            parts.append("Could you tell me " + ", and ".join(missing) + "?")
        else:
            request = (
                WalkingWindow(point=ctx.point, day=ctx.day, start=ctx.start, end=ctx.end)
                if ctx.start and ctx.end
                else ForecastDay(point=ctx.point, day=ctx.day)
            )
            data = point_forecast(request)
            if "live" in answer:
                answer["notice_result"] = answer["live"]
            answer["live"] = data
            parts.append(weather_answer(data))
            answer["evidence"] = data.get("planning_evidence", [])
            if data.get("source_review_warning"):
                answer["warnings"].append(data["source_review_warning"])
            ctx.awaiting = False
    else:
        ctx.awaiting = False
    answer.update(answer="\n\n".join(parts), chat_context=ctx.model_dump(mode="json"))
    return answer
