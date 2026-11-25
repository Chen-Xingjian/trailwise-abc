"""Compare specific published ABC schedules, counting mixed days once."""

import json
import re
from importlib.resources import files
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.distance import distance_followup
from app.packing import is_packing_request
from app.planning import DAY_COUNT, DAY_NUMBERS, day_number
from app.preparation import TRAINING_REQUEST, contact_question, practice_question
from app.turn_context import OTHER_ROUTE

CATALOG = json.loads(files("app").joinpath("abc_itineraries.json").read_text(encoding="utf-8"))
RECORDS = {record["key"]: record for record in CATALOG["records"]}
NAMES = {
    "jhinu": r"jhinu(?: danda)?",
    "siwai": "siwai",
    "ghandruk": "ghandruk",
    "nayapul": "nayapul|birethanti",
    "poon": "poon hill|ghorepani",
}
ROUTE_TERMS = {
    "siwai": "Siwai",
    "jhinu": "Jhinu Danda",
    "ghandruk": "Ghandruk",
    "nayapul": "Nayapul",
    "poon": "Poon Hill",
}
CHOICE = re.compile(
    r"\b(?:which|what) (?:abc |trekking )?(?:routes?|versions?|options?|approach|trek|one)\b|"
    r"\b(?:recommend|choose|suit(?:s|able)?|fit(?:s)?)\b.*\b(?:routes?|version|days?|options?)\b|"
    r"\bcompare\b.*\b(?:itineraries|days|schedules|how long|durations?|options?)\b",
    re.I,
)
DETAIL = re.compile(
    r"day.by.day|daily (?:plan|stages|stops|itinerary|schedule)|each day|"
    r"\b(?:itinerary|itineraries|schedule|stages|overnights|endpoints|how many days|"
    r"where .* (?:start|finish)|how long does .* take)\b",
    re.I,
)


class PlanContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keys: list[Literal["jhinu", "siwai", "ghandruk", "nayapul", "poon"]] = Field(
        default_factory=list, max_length=5
    )
    suggested: Literal["jhinu", "siwai", "ghandruk", "nayapul", "poon"] | None = None
    stage: int | None = Field(None, ge=1, le=99)
    days: float | None = Field(None, ge=0)
    basis: Literal["unknown", "walking", "pokhara", "travel"] = "unknown"

    def active_key(self):
        return self.keys[0] if len(self.keys) == 1 else self.suggested


def plan_places(context):
    if not (key := context.active_key()):
        return []
    record = RECORDS[key]
    if context.stage and context.stage <= len(record["days"]):
        day = record["days"][context.stage - 1]
        movement = day["walk"] or day["transfer"]
        return [
            place.replace("ABC", "Annapurna Base Camp").split(" via ")[0]
            for place in movement.split(" → ")
        ][:3]
    return [record["walking_start"].split(" (")[0]]


def matching_routes(text):
    return [key for key, pattern in NAMES.items() if re.search(rf"\b(?:{pattern})\b", text, re.I)]


def counts(record):
    days = record["days"]
    walking = sum(bool(day["walk"]) for day in days)
    mixed = sum(bool(day["transfer"] and day["walk"]) for day in days)
    return walking, mixed


def duration(record):
    walking, mixed = counts(record)
    if not record["pokhara_return_documented"]:
        return f"{walking} recorded walking days; total with travel from Pokhara unknown"
    road_only = len(record["days"]) - walking
    return (
        f"{len(record['days'])} days from Pokhara and back: {walking} with walking "
        f"({walking - mixed} trail-only, {mixed} with a drive), {road_only} drive-only"
    )


def day_activities(day):
    activities = []
    if day["walk"]:
        activities.append("Walk " + day["walk"])
    if day["transfer"]:
        activities.append("Drive " + day["transfer"])
        if day["transfer"].endswith("before walking"):
            activities.reverse()
    return ". ".join(activities) + "."


def daily(record, stage=None, *, details=None):
    lines = [
        f"**{record['label']}** · {record['publisher']}. Walking endpoints: "
        f"{record['walking_start']} to {record['walking_finish']}. {duration(record)}."
    ]
    for number, day in enumerate(record["days"], 1):
        if stage is not None and stage != number:
            continue
        line = f"Day {number} · " + day_activities(day)
        if details is not None:
            note = details.get(number) or day.get("walking_time_note")
            line = "- " + line + (" " + note if note else "")
        lines.append(line)
    if stage is not None and stage > len(record["days"]):
        lines.append("This published itinerary has no such day.")
    return "\n".join(lines) + "\n\n" + record["qualification"]


class PriorPlan(BaseModel):
    """The selected reply was a plan. Budget fields come from its walking-budget summary."""

    days: float | None = Field(None, ge=0, allow_inf_nan=False)
    origin: Literal["requested", "default"] | None = None


EXPAND_PLAN = re.compile(
    r"\b(?:detailed|full|expanded|step.by.step|day.by.day) (?:daily |trek |hiking |walking )?"
    r"(?:plan|itinerary|schedule|breakdown)\b|\bday.by.day\b|"
    r"\b(?:break|spell|flesh|lay) (?:it|that|this|the plan) (?:down|out)\b|"
    r"\b(?:more detail(?:ed)?|each day|every day|one day at a time|day.to.day|elaborate|expand on (?:it|that|the plan))\b", re.I
)


def recorded_clocks(number, facts):
    clocks = []
    ids = []
    for suffix, label in (("M", "moving"), ("E", "including stops")):
        fid = f"KT-D{number}-{suffix}"
        if fid in facts:
            clocks.append(f"{facts[fid]['value']['original_display']} {label}")
            ids.append(fid)
    return ", ".join(clocks), ids


def expand_plan(question, parent, previous, release):
    if parent is None or not EXPAND_PLAN.search(question):
        return None
    if (is_packing_request(question) or OTHER_ROUTE.search(question)
            or re.search(r"forecast|weather|equipment|training|fitness|permit|distance|altitude|"
                         r"acclimati|food|gear|budget for|cost|price", question, re.I)
            or DAY_COUNT.search(question) or requested_stage(question.lower(), previous)):
        return None
    keys = matching_routes(question)
    if len(keys) > 1:
        return None
    key = keys[0] if keys else previous.active_key() if previous else None
    if key is None and parent.origin:
        key = "siwai"  # The budget summary is exclusively for the archived Siwai walk.
    if key is None:
        if previous:
            options = [RECORDS[k] for k in previous.keys] or list(RECORDS.values())
            return plan_result("Which itinerary would you like me to expand? " +
                               ", ".join(r["label"] for r in options) + ".", previous, options)
        return None
    context = (previous or PlanContext()).model_copy(update={"keys": [key], "suggested": None, "stage": None})
    if parent.origin == "requested":
        context.days, context.basis = parent.days, "walking"
    record = RECORDS[key]
    details = {}
    ids = set()
    parts = []
    walking, _ = counts(record)
    if parent.origin == "default" and parent.days is not None:
        parts.append(f"The earlier {parent.days:g} walking days were an example. "
                     f"This published itinerary has {walking} walking days.")
    elif context.days is not None and context.basis == "walking":
        gap = walking - context.days
        fit = (f"you would need {gap:g} more" if gap > 0 else
               f"you have {abs(gap):g} in reserve" if gap < 0 else "the day counts match")
        parts.append(f"You have {context.days:g} walking days. This itinerary uses {walking}, so {fit}.")
    if key == "siwai":
        chunks = {c["fact_id"]: c for c in release.chunks}
        facts = {f["fact_id"]: f for f in release.facts if f["scope"]["reference_id"] == "ABC-KT-06"}
        ids.update({"K07", "K08"} & chunks.keys())
        for number in range(1, len(record["days"]) + 1):
            clocks, clock_ids = recorded_clocks(number, facts)
            if clocks:
                details[number] = clocks + "."
                ids.update(clock_ids)
        if details:
            parts.append("The times below come from one KeiTreks trip. Use them to compare stages when planning your own pace.")
    else:
        arrival = next((i for i, day in enumerate(record["days"], 1) if walk_ends(day)[1] == "ABC"), None)
        if arrival:
            parts.append(f"Plan around day {arrival}, when this itinerary reaches Annapurna Base Camp. "
                         f"The remaining {len(record['days']) - arrival} days cover the return.")
        if not any(d.get("walking_time_note") for d in record["days"]):
            parts.append("The reviewed schedule gives daily stops and transfers. Daily walking times are unverified.")
    parts.append(daily(record, details=details))
    result = plan_result("\n\n".join(parts), context, [record])
    result["evidence"] = [c for c in release.chunks if c["fact_id"] in ids]
    return result


def budget_basis(text):
    if re.search(
        r"(?:exclud\w*|without|apart from|after deducting) (?:the |all )?(?:road |return )?(?:transport|transfers?|travel)|"
        r"\b(?:net|actual|full) (?:walking|trekking|hiking) days|(?:walking|trekking|hiking) days|"
        r"days (?:on foot|(?:just |only )?for (?:walking|hiking|trekking))|walking only",
        text,
    ):
        return "walking"
    if re.search(
        r"pokhara (?:to pokhara|and back)|(?:start|begin).*pokhara.*(?:finish|end|return).*pokhara|(?:round trip|return trip|round.trip) from pokhara|both (?:in|at) pokhara",
        text,
    ) and not re.search(r"kathmandu|international|airport|flight", text):
        return "pokhara"
    if re.search(
        r"travel|transfers?|transport|holiday|in total|calendar|flights?|kathmandu|door.to.door",
        text,
    ):
        return "travel"
    return "unknown"


ORDINALS = "first second third fourth fifth sixth seventh eighth ninth tenth".split()


def requested_stage(text, previous):
    numbered = re.search(r"\bday[ -]+(\d{1,2}|" + "|".join(DAY_NUMBERS[1:]) + r")\b", text)
    if numbered:
        return int(day_number(numbered[1])) or None
    numeric_ordinal = re.search(r"\b(\d{1,2})(?:st|nd|rd|th) day\b", text)
    if numeric_ordinal:
        return int(numeric_ordinal[1]) or None
    ordinal = re.search(r"\b(" + "|".join(ORDINALS) + r") day\b", text)
    if ordinal:
        return ORDINALS.index(ordinal[1]) + 1
    if re.search(r"\b(?:last|final) day\b", text):
        routes = matching_routes(text) or ([previous.active_key()] if previous else [])
        if len(routes) == 1 and routes[0]:
            return len(RECORDS[routes[0]]["days"])
    return None


def directed_stage(text):
    # Match endpoint names from all five schedules so a foreign pair is detectable.
    match = STAGE_PAIR.search(text)
    if not match:
        return None
    return tuple("abc" if p == "annapurna base camp" else p for p in match.groups())


def variant_answer(question, previous, focus, after_distance=False, selected=None):
    if (
        is_packing_request(question)
        or TRAINING_REQUEST.search(question)
        or practice_question(question)
    ):
        return None
    text = question.strip().lower().replace("’", "'")
    timing = re.search(
        r"how long|how many hours|walking time|elapsed time|how far|distance|ascent|descent", text
    )
    stage = requested_stage(text, previous)
    day_number_requested = stage or (previous.stage if previous else None)
    if (
        previous
        and previous.active_key()
        and previous.active_key() != "siwai"
        and day_number_requested
        and timing
        and not OTHER_ROUTE.search(text)
        and not matching_routes(text)
        and not re.search(r"weather|forecast|notice|\b(?:whole|total|route|entire trek)\b", text)
    ):
        rec = RECORDS[previous.active_key()]
        if 1 <= day_number_requested <= len(rec["days"]):
            day = rec["days"][day_number_requested - 1]
            movement = day["walk"] or day["transfer"]
            reversed_trip = re.search(
                r"reverse|opposite direction|other way|other direction|backwards", text
            )
            start, end = walk_ends(day)
            if start and end:
                reversed_trip = reversed_trip or re.search(
                    rf"\b{re.escape(end.casefold())}\s+(?:to|towards?|→)\s+{re.escape(start.casefold())}\b",
                    text,
                )
            if reversed_trip:
                return plan_result(
                    f"The published day {day_number_requested} runs {movement}. I have no checked measurement for that stage in reverse.",
                    previous,
                    [rec],
                )
            note = day.get("walking_time_note") if re.search(r"how long|hours|time", text) else None
            message = f"Day {day_number_requested} on the {rec['label']} itinerary: {movement}. "
            message += note or "I do not have a checked measurement for that stage in this guide."
            return plan_result(
                message, previous.model_copy(update={"stage": day_number_requested}), [rec]
            )
    if OTHER_ROUTE.search(text) or re.search(
        r"weather|forecast|equipment|training|first aid|sleeping bag|how far|kilomet|\bdistance\b|\b(?:permit|altitude|elevation|ascent|descent|water|snow|shoes|poles|cost|temperature)\b",
        text,
    ):
        return None
    keys = matching_routes(text)
    counts_in_text = [day_number(m[1]) for m in DAY_COUNT.finditer(text)]
    choice, detail = CHOICE.search(text), DETAIL.search(text)
    basis = budget_basis(text)
    contextual = previous is not None or after_distance
    overview = re.search(r"\b(?:overview|outline|big picture|in a nutshell|at a glance|brief summary|quick summary|summari[sz]e)\b", text)
    plain_plan = not contextual and keys != ["siwai"] and re.search(r"\bplan\b", text)
    if (len(keys) == 1 and (overview or plain_plan) and not counts_in_text and not stage
            and not choice and not EXPAND_PLAN.search(text) and not re.search(r"daily|stages", text)):
        record = RECORDS[keys[0]]
        arrival = next(i for i, day in enumerate(record["days"], 1) if walk_ends(day)[1] == "ABC")
        answer = (f"{record['publisher']} lists {duration(record)}. "
                  f"The walk starts at {record['walking_start']}, reaches Annapurna Base Camp on day {arrival}, "
                  f"and finishes at {record['walking_finish']}.")
        return plan_result(answer, PlanContext(keys=keys), [record])
    fragment = distance_followup(text) or (
        previous
        and re.fullmatch(
            r"(?:yes[, ]*)?(?:show (?:me )?)?(?:the |its )?(?:plan|details|daily stops)[.!? ]*",
            text,
        )
    )
    standalone_budget = bool(
        re.fullmatch(r"(?:i|we) (?:only )?have (?:only )?.{1,24} days?[.!? ]*", text)
        and counts_in_text
    )
    all_daily = bool(
        detail
        and re.search(
            r"\b(?:all|each|every) (?:the |five )?(?:routes?|variants?|versions?|options?|itineraries)\b",
            text,
        )
    )
    switch = bool(
        previous
        and keys
        and re.search(
            r"\b(?:switch|choose|pick|instead|go with|go for|change to|use|what about|how about)\b",
            text,
        )
    )
    planning = bool(switch or choice or detail or re.search(r"\bplan\b", text))
    if not (
        choice
        or standalone_budget
        or all_daily
        or (planning and (keys or contextual))
        or (
            contextual
            and (counts_in_text or stage or (previous and (fragment or basis != "unknown")))
        )
    ):
        return None
    if (
        not contextual
        and not (choice or standalone_budget or all_daily)
        and (not keys or (keys == ["siwai"] and not detail))
    ):
        return None  # Keep the evaluated Siwai planning flow for a fixed itinerary.
    if not contextual and not keys and not counts_in_text and not detail:
        return None
    if not keys and after_distance and not (previous and previous.keys):
        keys = matching_routes(" ".join(focus.places))
    if (
        not keys
        and previous
        and previous.suggested
        and not choice
        and (detail or stage or fragment)
    ):
        keys = [previous.suggested]
    if not keys:
        keys = list(previous.keys) if previous else (["siwai"] if selected == "ABC-KT-06" else [])
    context = PlanContext(
        keys=keys,
        days=previous.days if previous else None,
        basis=previous.basis if previous else "unknown",
    )
    if counts_in_text:
        context.days = counts_in_text[-1]
    if basis != "unknown":
        context.basis = basis
    records = [RECORDS[k] for k in keys] if keys else list(RECORDS.values())
    parts = []
    if len(set(counts_in_text)) > 1:
        net = re.search(r"(\d+|[a-z]+) (?:full |net )?(?:walking|hiking|trekking) days?\b", text)
        if net and DAY_COUNT.fullmatch(net[0]):
            context.days, context.basis = day_number(net[1]), "walking"
        elif calendar := re.search(r"(\d+|[a-z]+) (?:calendar|total) days", text):
            if DAY_COUNT.fullmatch(calendar[0].replace("total", "calendar")):
                context.days, context.basis = day_number(calendar[1]), "travel"
                parts.append(
                    "Your calendar budget includes travel. The number of full walking days is still unconfirmed."
                )
        else:
            context.days = None
            parts.append("Which number is the time available for this trek after other travel?")
    custom = len(keys) > 1 and not re.search(r"\b(?:or|compare|versus|vs|between)\b", text)
    sources = list(records)
    if custom:
        parts.append(
            "I can show the published schedules separately. I have no checked day-by-day plan combining those specific stops."
        )
    fits = []
    stage_only = bool(stage and not counts_in_text and len(records) == 1)
    if context.days is not None and not custom and not stage_only:
        days = context.days
        walking = context.basis == "walking"
        fits = [
            r
            for r in records
            if (walking or r["pokhara_return_documented"])
            and (counts(r)[0] if walking else len(r["days"])) <= days
        ]
        if fits:
            # Prefer a slower published schedule with a spare day when one fits.
            with_margin = [r for r in fits if (counts(r)[0] if walking else len(r["days"])) < days]
            recommendation = max(with_margin or fits, key=lambda r: counts(r)[0])
            context.suggested = recommendation["key"]
            if context.basis == "travel":
                lead = f"A {days:g}-day door-to-door fit is unconfirmed. One option to compare from Pokhara is"
            elif context.basis == "unknown":
                lead = f"If your {days:g} days start and end in Pokhara, one published option is"
            elif walking:
                lead = f"For {days:g} walking days, one published option is"
            else:
                lead = f"Within {days:g} days from Pokhara and back, one published option is"
            parts.append(
                f"{lead} **{recommendation['label']}**. {recommendation['publisher']} lists {duration(recommendation)}."
            )
            if recommendation["key"] == "jhinu":
                parts.append(
                    "Its fourth day is a long descent from base camp to Sinuwa. The five-day schedule includes no reserve day. If that pace or the jeep connections are doubtful, add time or choose a shorter outing."
                )
        else:
            parts.append(
                f"I can’t confirm a complete trip on the selected schedule within {days:g} days "
                + ("of walking." if walking else "including travel.")
            )
            parts.append(
                "Allow more time or plan a shorter out-and-back with a turnaround before base camp."
            )
            if keys and "jhinu" not in keys and days == 5:
                short = RECORDS["jhinu"]
                sources.append(short)
                parts.append(
                    "If you can change trailheads, Haven Holidays lists a five-day Jhinu Danda return from Pokhara. It uses both end days for walking and jeep travel and leaves no reserve day."
                )

        if context.basis == "unknown":
            parts.append(
                "Are these walking days, or does the budget include getting to and from the trail?"
            )
        elif context.basis == "travel":
            parts.append(
                "When can you leave Pokhara and when must you be back there? Travel outside Pokhara needs a separate allowance."
            )
    show_daily = bool(keys and (detail or stage or fragment or planning and not counts_in_text))
    if stage and day_number_requested:
        context.stage = day_number_requested
    duration_comparison = bool(
        keys
        and not stage
        and not all_daily
        and (switch or re.search(r"how long|how many days|duration|compare.*days", text))
        and not re.search(r"day.by.day|daily|each day|stages", text)
    )
    if duration_comparison:
        parts.insert(0, "\n".join(f"- **{r['label']}** — {duration(r)}." for r in records))
    elif show_daily or all_daily:
        parts.extend(daily(r, stage) for r in records)
    elif not parts or len(records) > 1 or not context.days or not fits:
        parts.append("\n".join(f"- **{r['label']}** — {duration(r)}." for r in records))
    if not keys and not context.days:
        parts.append("Which starting point would you like the daily stages for?")
    return plan_result("\n\n".join(parts), context, sources)


def itinerary_source(record):
    return {k: record[k] for k in ("label", "publisher", "url", "locator")}


def selected_schedule(key):
    record = RECORDS[key]
    summary = (
        f"For planning, {record['publisher']} lists a separate itinerary with "
        f"{duration(record)}. Walking endpoints: {record['walking_start']} to {record['walking_finish']}."
    )
    if key == "nayapul":
        summary += " Starting at Birethanti itself would need a separate schedule."
    return summary, itinerary_source(record)


def plan_result(answer, context, sources):
    return {
        "answer_kind": "variant_plan",
        "mode": "rag",
        "answer": answer,
        "evidence": [],
        "warnings": [],
        "variant_context": context.model_dump(),
        "itinerary_sources": [itinerary_source(r) for r in sources],
    }


def walk_ends(day):
    if not day["walk"]:
        return None, None
    places = day["walk"].split(" via ")[0].split(" → ")
    return places[0], places[-1]


_stage_names = {
    place.casefold()
    for r in RECORDS.values()
    for day in r["days"]
    for place in walk_ends(day)
    if place
} | {"annapurna base camp", "pokhara"}
_place = "|".join(re.escape(p) for p in sorted(_stage_names, key=len, reverse=True))
STAGE_PAIR = re.compile(rf"\b({_place})\s*(?:-to-|\bto\b|→|towards?)\s*({_place})\b")


def stage_selection(text, record, previous_stage):
    """Calendar ordinals include transfers; walking ordinals skip transfer-only days."""
    days = record["days"]
    walking = [i for i, d in enumerate(days, 1) if d["walk"]]
    ordinal = re.search(
        r"\b(" + "|".join(ORDINALS) + r") (?:walking (?:day|stage|leg)|day on foot|hiking day)",
        text,
    )
    if ordinal:
        index = ORDINALS.index(ordinal[1])
        if index < len(walking):
            return walking[index]
    if re.search(r"village (?:sightseeing|visit)|sightseeing day", text):
        return walking[0]
    if previous_stage and re.search(
        r"\bnext (?:walking |hiking )?(?:day|leg|stage)|following (?:stage|leg|day)|(?:the )?one after (?:that|this)",
        text,
    ):
        return next((n for n in walking if n > previous_stage), None)
    if previous_stage and re.search(
        r"previous (?:walking )?(?:stage|leg|day)|one before (?:that|this)", text
    ):
        return next((n for n in reversed(walking) if n < previous_stage), None)
    if re.search(r"\bafter\b|when we leave|straight after", text):
        matches = []
        for n in walking:
            start, _ = walk_ends(days[n - 1])
            place = (
                r"(?:abc|(?:annapurna )?base camp)" if start == "ABC" else re.escape(start.lower())
            )
            if re.search(
                r"(?:night|sleeping|stop|stay|leave|overnight|after)(?: back)?(?: in| at)? (?:the )?"
                + place
                + r"\b",
                text,
            ):
                matches.append(n)
        if len(matches) > 1 and re.search(r"back|home|return|drive|wheels", text):
            camp = next((i for i in walking if walk_ends(days[i - 1])[1] == "ABC"), None)
            matches = [i for i in matches if camp and i > camp]
        if len(matches) == 1:
            return matches[0]
    return None


def comparison_followup(question, previous):
    """Keep the selected itinerary when a different itinerary is offered as a source."""
    active = previous.active_key() if previous else None
    if not active:
        return None
    text = question.casefold().replace("’", "'")
    if re.search(r"(?:let's|please|now|want to|i'll|i will) (?:switch|change|follow|take)|switch (?:me |us )?to", text):
        return None
    others = [k for k in matching_routes(text) if k != active]
    if "keitreks" in text and active != "siwai" and "siwai" not in others:
        others.append("siwai")
    if not others or not re.search(r"time|timing|duration|hours|minutes|gps|mileage|distance|ascent", text):
        return None
    if not re.search(r"paste|borrow|substitut|transfer|copy|apply|reuse|same as|valid for|stand in|use .*(?:for|on|instead|here)|compare", text):
        return None
    target = RECORDS[active]
    records = [target, *(RECORDS[k] for k in others)]
    context = previous.model_copy()
    stage = requested_stage(text, None)
    if re.search(r"(?:last|final|closing|return) (?:walking )?(?:day|leg|stage|section)", text):
        stage = len(target["days"])
    detail = target["label"]
    if stage and 1 <= stage <= len(target["days"]):
        context.stage = stage
        detail += f", day {stage} ({target['days'][stage - 1]['walk'] or 'transfer'})"
    names = " and ".join(r["label"] for r in records[1:])
    answer = (f"Keep {detail} as your itinerary. A measurement from {names} does not establish "
              "the value for your stage. Check a record for your itinerary with the same walking endpoints, direction and measurement.")
    return plan_result(answer, context, records)


def focused_day(record, number, context, release):
    day = record["days"][number - 1]
    parts = [f"**Day {number} · {record['label']}**", day_activities(day)]
    ids = []
    if record["key"] == "siwai":
        facts = {f["fact_id"]: f for f in release.facts
                 if f["scope"]["reference_id"] == "ABC-KT-06" and f["scope"].get("stage_index") == number}
        clocks, ids = recorded_clocks(number, facts)
        if clocks:
            parts.append(f"KeiTreks recorded {clocks} on this walk.")
        for fid, fact in facts.items():
            if fact["predicate"] in {"approximate_cumulative_ascent", "approximate_cumulative_descent"}:
                parts.append(fact["statement_en"])
                ids.append(fid)
    elif note := day.get("walking_time_note"):
        parts.append(note)
    if not day["walk"]:
        parts.append(f"This is a transfer day. The first walking stage is {next(d['walk'] for d in record['days'] if d['walk'])}.")
    elif number > 1 and not record["days"][number - 2]["walk"]:
        parts.append(f"Day {number - 1} is the approach to {record['walking_start']}; walking starts on day {number}.")
    if day["transfer"] and day["walk"] and number == len(record["days"]):
        parts.append("Allow time for the drive after the walk. The reviewed schedule gives no confirmed pickup or arrival time.")
    result = plan_result("\n\n".join(parts), context.model_copy(update={"stage": number}), [record])
    result["evidence"] = [c for c in release.chunks if c["fact_id"] in ids]
    return result


def route_followup(question, previous, release):
    """Resolve pointers against the selected publisher's ordered stages before broad retrieval."""
    text = question.casefold().replace("’", "'")
    pair = directed_stage(text)
    keys = matching_routes(STAGE_PAIR.sub("", text) if pair and previous else text)
    # A named village in a numbered stage can also be another itinerary's trailhead.
    active = previous.active_key() if previous else None
    number = requested_stage(text, previous)
    if active and keys and number and re.search(r"\b(?:leave|leaving|reach|reaching|pass|passing|overnight in|sleep in)\b", text):
        days = RECORDS[active]["days"]
        if number <= len(days) and not re.search(r"switch|instead|other (?:route|itinerary)|version|approach", text):
            day = days[number - 1]
            waypoints = matching_routes((day["walk"] or "") + " " + (day["transfer"] or ""))
            if all(k in waypoints for k in keys):
                keys = [active]
    if not keys and "keitreks" in text:
        keys = ["siwai"]
    compare = re.search(r"later|earlier|higher numbered|sooner", text)
    if len(keys) > 1 and compare and re.search(r"base camp|\babc\b", text):
        arrivals = {}
        for key in keys:
            day = next(
                (i for i, d in enumerate(RECORDS[key]["days"], 1) if walk_ends(d)[1] == "ABC"), None
            )
            if day is None:
                return None
            arrivals[key] = day
        target = (min if re.search(r"earlier|sooner", text) else max)(arrivals.values())
        winners = [k for k, n in arrivals.items() if n == target]
        suggested = winners[0] if len(winners) == 1 else None
        answer = (
            ". ".join(f"{RECORDS[k]['label']} reaches ABC on day {n}" for k, n in arrivals.items())
            + "."
        )
        answer += (
            f" Choose the {RECORDS[suggested]['label']} itinerary for that criterion."
            if suggested
            else " They arrive on the same numbered day."
        )
        return plan_result(
            answer, PlanContext(keys=keys, suggested=suggested), [RECORDS[k] for k in keys]
        )
    key = keys[0] if len(keys) == 1 else previous.active_key() if previous and not keys else None
    if not key:
        if (
            previous
            and len(previous.keys) > 1
            and not previous.active_key()
            and not keys
            and re.search(
                r"next (?:day|walking stage|leg)|that (?:stage|leg)|where (?:do|does) .*finish",
                text,
            )
        ):
            choices = [RECORDS[k] for k in previous.keys]
            return plan_result(
                "Which itinerary should I use: " + " or ".join(r["label"] for r in choices) + "?",
                previous,
                choices,
            )
        return None
    record = RECORDS[key]
    same = previous and previous.active_key() == key
    context = (
        previous.model_copy(update={"keys": [key], "suggested": None})
        if same
        else PlanContext(keys=[key])
    )
    if (
        key != "siwai"
        and pair
        and re.search(
            r"how long|how many hours|walking time|elapsed|duration|distance|how far|ascent|descent",
            text,
        )
        and "pokhara" not in pair
    ):
        exact = [
            i
            for i, d in enumerate(record["days"], 1)
            if d["walk"] and tuple(v.casefold() for v in walk_ends(d)) == pair
        ]
        specified = requested_stage(text, previous)
        if specified:
            exact = [i for i in exact if i == specified]
        if len(exact) != 1 or re.search(
            r"reverse|other direction|opposite direction|backwards", text
        ):
            return plan_result(
                f"I have no checked measurement matching those endpoints and direction on the {record['label']} schedule.",
                context,
                [record],
            )
        idx = exact[0]
        day = record["days"][idx - 1]
        note = (
            day.get("walking_time_note")
            if re.search(r"how long|how many hours|walking time|duration", text)
            and not re.search(r"elapsed|door.to.door|including|transfer", text)
            else None
        )
        return plan_result(
            f"Day {idx} is {day['walk']}. "
            + (
                note or "I do not have a checked value for the requested measurement on this stage."
            ),
            context.model_copy(update={"stage": idx}),
            [record],
        )
    old = context.stage
    stage = stage_selection(text, record, old)
    numbered_day = requested_stage(text, context)
    day_plan = re.search(
        r"what(?:'s| is) (?:on|the plan|planned)|what (?:do|will|happens)|how does .*day work|"
        r"walk .*through|talk .*through|tell me about|what does .*look like|what are we doing|show|outline|describe|(?:more )?detail|"
        r"(?:the )?(?:first|last|final|second|third|fourth|fifth|sixth|seventh|eighth) (?:walking|hiking) day|"
        r"^(?:and |what about |how about )?(?:on )?day ", text
    )
    if (day_plan and (stage or numbered_day) and not OTHER_ROUTE.search(text)
            and not re.search(r"weather|forecast|train|pack|gear|notice|permit|meet|join|contact|"
                              r"how long|how (?:many|much)|what time|distance|ascent|descent|"
                              r"duration|minutes|hours|elevation|altitude|reverse", text)):
        number = stage or numbered_day
        if 1 <= number <= len(record["days"]):
            return focused_day(record, number, context, release)
    if stage is None and re.search(r"day.s (?:walk|stage|leg)|(?:show|describe|outline).{0,45}(?:walk|stage|leg)|where .*walk", text):
        stage = requested_stage(text, context)
    contact = contact_question(text)
    finish = bool(
        re.search(
            r"(?:last|final) walking (?:day|leg|stage).*finish|walking finish|leave the trail|finish by (?:vehicle|road)|back to pokhara.*walking|town .*by road",
            text,
        )
    )
    transfer_clock = (
        re.search(r"jeep|ride|transfer|drive|pokhara", text)
        and re.search(
            r"how long|how many hours|what time|when .*arrive|\b\d+\s*(?:h|hours?|minutes?)\b|\d+h\d+",
            text,
        )
        and re.search(r"back|return|after walk|from .* to pokhara|arriv", text)
    )
    return_query = transfer_clock or bool(
        re.search(r"\b(?:return|arrival|arrive|back|finish)\b", text)
        and re.search(r"arrival time|what time|how long|when .*arrive|how many hours", text)
    )
    if re.search(r"reverse|other direction|opposite direction", text):
        return None
    if (
        finish
        or transfer_clock
        or (contact and same and re.search(r"finish|those two stops|back in town|endpoints", text))
        or (
            return_query and key != "siwai" and not re.search(r"stage|leg|day \d|from .+ to ", text)
        )
    ):
        stage = len(record["days"])
    training = re.search(r"training|practi[cs]|trained|rehears", text) and re.search(
        r"climb|uphill|descen|downhill|pack", text
    )
    if (
        training
        and old
        and same
        and not stage
        and re.search(r"that (?:particular )?day|this (?:leg|day|section)|that (?:leg|stage)", text)
    ):
        stage = old
    if stage is None or not 1 <= stage <= len(record["days"]):
        return None
    context.stage = stage
    day = record["days"][stage - 1]
    start, end = walk_ends(day)
    activity = day["walk"] or f"a road transfer from {day['transfer']}, with no walking stage listed"
    parts = [f"{record['publisher']} lists day {stage} of the {record['label']} itinerary as {activity}."]
    if stage == next(i for i, d in enumerate(record["days"], 1) if d["walk"]) and stage > 1:
        parts.append(
            f"Day 1 is the approach to {record['walking_start']}; walking starts on day {stage}."
        )
    if re.search(r"\b(?:meet|meeting|wait|join|note)\b", text) and end:
        parts.append(f"The meeting point at the end of that stage is {end}.")
    if day["transfer"] and day["walk"]:
        parts.append(f"The published road transfer is {day['transfer']}.")
    if return_query:
        parts.append(
            "There is no verified total duration or arrival time for that return in the reviewed schedule. A time for one walking stage cannot establish it."
        )
    ids = []
    if training:
        if day.get("walking_time_note"):
            parts.append(day["walking_time_note"])
        ids.append("F03")
    if contact:
        ids.append("F05")
    facts = {f["fact_id"]: f for f in release.facts}
    ids = [fid for fid in ids if fid in facts]
    parts.extend(f"{facts[fid]['statement_en']} [{fid}]" for fid in ids)
    result = plan_result(" ".join(parts), context, [record])
    result["evidence"] = [c for c in release.chunks if c["fact_id"] in ids]
    return result
