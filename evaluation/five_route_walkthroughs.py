"""Replay five independent UI-style conversations and check answer content and selected route."""

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from compare_chat_branches import run

# (selection, daily plan, packing, weather, optional clarification reply, fitness, day recall)
DIALOGUES = {
    "jhinu": (
        "I'll take the Jhinu Danda option.",
        "Could you walk me through the itinerary?",
        "What should go in my daypack for this one?",
        "Will it rain at Deurali tomorrow?",
        None,
        "How should I train for this trip?",
        "Back to the route, where do we walk on day four again?",
    ),
    "siwai": (
        "From Siwai",
        "Can I see the day-by-day plan?",
        "What should I bring for this plan?",
        "How cold will it be at base camp tomorrow?",
        None,
        "I mostly walk on flat ground. How can I get in shape for this hike?",
        "Remind me where the fourth day takes us.",
    ),
    "ghandruk": (
        "Let's go with the Ghandruk one.",
        "What does each day look like?",
        "Any essentials I should pack?",
        "What's the weather looking like in Chhomrong tomorrow?",
        None,
        "What kind of training would you suggest before I go?",
        "Going back to the first day, are we walking or driving?",
    ),
    "nayapul": (
        "From Nayapul/Birethanti — 90–95 km",
        "Can you lay out the daily stages?",
        "Could you give us a gear checklist for this itinerary?",
        "Weather in Sinuwa tomorrow?",
        "Use Deurali instead, please.",
        "What can I do to prepare physically?",
        "Where are we walking on the second day again?",
    ),
    "poon": (
        "I'd like the one via Poon Hill.",
        "Show me the stops day by day.",
        "What do we need to take along on this hike?",
        "Any chance of rain at Annapurna Base Camp the day after tomorrow?",
        None,
        "How do I build up my stamina before the trek?",
        "And on the last day, how do we get back?",
    ),
}
STAGE = {"jhinu": 4, "siwai": 4, "ghandruk": 1, "nayapul": 2, "poon": 8}
POINT = {
    "jhinu": "Deurali",
    "siwai": "ABC",
    "ghandruk": "Chhomrong",
    "nayapul": "Deurali",
    "poon": "ABC",
}
RECORDS = {
    r["key"]: r
    for r in json.loads(
        (Path(__file__).resolve().parents[1] / "app/abc_itineraries.json").read_text()
    )["records"]
}


def cases():
    for route, questions in DIALOGUES.items():
        previous = None
        for topic, text in zip(
            ("menu", "select", "plan", "gear", "weather", "point", "fitness", "day"),
            ("How far is the Annapurna Base Camp trek?", *questions),
            strict=True,
        ):
            if text:
                key = f"{route}.{topic}"
                yield key, previous, text, []
                previous = key


def failures(row):
    route, topic = row["id"].split(".")
    record = RECORDS[route]
    answer, plan, live = row["answer"], row["plan"] or {}, row["live"] or {}
    checks = {}
    if topic != "menu":
        checks["selected route"] = plan.get("keys") == [route]
    if topic == "menu":
        checks["five choices"] = all(
            name in answer for name in ("Jhinu", "Siwai", "Ghandruk", "Nayapul", "Poon Hill")
        )
    elif topic == "select":
        checks["selected route named"] = record["label"].split()[0] in answer or (
            route == "poon" and "Poon Hill" in answer
        )
    elif topic in {"plan", "day"}:
        days = record["days"]
        indexes = range(len(days)) if topic == "plan" else [STAGE[route] - 1]
        lines = {int(n): line for n, line in re.findall(r"^Day (\d+) · (.+)$", answer, re.M)}
        checks["published movements"] = all(
            all(
                value in lines.get(i + 1, "")
                for value in (days[i]["walk"], days[i]["transfer"])
                if value
            )
            for i in indexes
        )
        checks["itinerary source"] = any(
            x["url"] == record["url"] and x["locator"] for x in row["itinerary_sources"]
        )
        if topic == "day":
            checks["selected day only"] = (
                plan.get("stage") == STAGE[route] and len(re.findall(r"Day \d+ ·", answer)) == 1
            )
    elif topic == "gear":
        checks["useful grounded gear"] = (
            "headlamp" in answer.lower()
            and {"G01", "G02"} <= set(row["facts"])
            and "Day 1 ·" not in answer
        )
        checks["gear scope"] = route == "siwai" or not {"G06", "G07"}.intersection(row["facts"])
    elif topic == "fitness":
        checks["grounded training advice"] = (
            "F03" in row["facts"]
            and "pack" in answer.lower()
            and re.search("climb|ascent|uphill", answer, re.I)
            and "Day 1 ·" not in answer
        )
    elif topic == "weather" and route == "nayapul":
        checks["unsupported point clarified"] = (
            row["kind"] == "live_clarification" and "Deurali" in answer and not live
        )
    else:
        checks["point"] = live.get("point") == POINT[route]
        checks["provider result or explicit unavailability"] = live.get("status") in {
            "forecast",
            "unavailable",
        }
        date = live.get("checked_at_utc")
        checks["Nepal date"] = (
            date
            and live["local_date"]
            == (
                datetime.fromisoformat(date).astimezone(ZoneInfo("Asia/Kathmandu")).date()
                + timedelta(days=2 if route == "poon" else 1)
            ).isoformat()
        )
    return [name for name, passed in checks.items() if not passed]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--score-only", action="store_true")
    args = parser.parse_args()
    if not args.score_only:
        with args.output.open("x") as stream:
            run(stream, cases(), assess=failures)
    rows = [json.loads(line) for line in args.output.read_text().splitlines()]
    assert [row["id"] for row in rows] == [key for key, *_ in cases()]
    for row in rows:
        print(row["id"], ", ".join(failures(row)) or "PASS")
    print("Passed", sum(not failures(row) for row in rows), "of", len(rows))
