"""Select measured fields from the reviewed KeiTreks stage in the requested direction."""

import re

from app.variant_plans import RECORDS, PlanContext, directed_stage, matching_routes, requested_stage

PREDICATES = {
    "gain": "approximate_cumulative_ascent",
    "moving": "moving_time",
    "elapsed": "door_to_door_elapsed_time",
}
LABELS = {"gain": "cumulative ascent", "moving": "moving time", "elapsed": "door-to-door time"}
REVERSE = re.compile(
    r"\brevers(?:e|ed)|other (?:way|direction)|opposite direction|way back|return direction"
)
GAIN = re.compile(
    r"\bascent\b|(?:elevation|altitude|height|vertical) gain|gain(?:ed)? (?:in )?(?:elevation|altitude|height)|"
    r"how (?:much|many (?:vertical )?met(?:re|er)s?).{0,55}(?:climb|uphill|gain|ascend)|"
    r"(?:climb|gain|uphill).{0,24}(?:in met(?:re|er)s|in total)|total (?:climb|uphill)|how much (?:vertical|uphill)"
)
MOVING = re.compile(
    r"\bmoving\b|on the move|actually (?:walk(?:ing)?|hik(?:e|ing))|actual walking time|walking.only|time (?:spent )?(?:walking|on foot)|"
    r"without (?:stopping|(?:the )?(?:stops|breaks|rests))|excluding (?:the )?(?:stops|breaks|rests)"
)
ELAPSED = re.compile(
    r"elapsed|door.to.door|two clocks|start to finish|including (?:the |our |all )?(?:stops|breaks|rests)|"
    r"(?:with|counting) (?:the |all )?(?:stops|breaks|rests)|total (?:time|duration)|whole day take"
)
BREAK_CHECK = re.compile(r"(?:does|did|is|was|were) (?:that|this|it|those).*(?:breaks|stops|rests)")
TIME = re.compile(r"how long|how many (?:hours|minutes)|how much time|duration|walking time")
MINUTES = re.compile(r"\b(?:how many (?:total )?minutes|(?:in|as|of) (?:total )?minutes|minute count|total minutes|whole minutes|minutes only)\b")
CLOCK_EXPLANATION = re.compile(
    r"(?:what|which).{0,50}(?:mean|include|count)|(?:mean|include|count).{0,45}(?:stops?|breaks?|rests?)|"
    r"difference between|how.{0,50}differ|distinction|explain|defined|versus|\bvs\b"
)
OTHER_TOPIC = re.compile(
    r"\b(?:forecast|weather|train|training|practise|practice|gear|pack|jeep|drive|pickup|"
    r"descend|descent|downhill|distance|kilometres|kilometers)\b"
)


def requested_metrics(text):
    # Time to complete a climb and height gained during it are different quantities.
    names = []
    if GAIN.search(text) and not re.search(r"how much time.{0,28}climb", text):
        names.append("gain")
    if MOVING.search(text) or "two clocks" in text:
        names.append("moving")
    if ELAPSED.search(text):
        names.append("elapsed")
    if TIME.search(text) and not {"moving", "elapsed"}.intersection(names):
        names.extend(("moving", "elapsed"))
    return names


def stage_measurement(question, release, focus, parent_focus, plan, reference):
    text = question.casefold().replace("’", "'")
    if (plan and plan.active_key() == "siwai" and parent_focus and parent_focus.metric
            and re.search(r"which (?:way|direction)|what direction|which endpoints|where (?:did|was) that .*(?:from|start|finish)", text)
            and not directed_stage(text) and not REVERSE.search(text) and not matching_routes(text)):
        record = next((f for f in release.facts if f["predicate"] == PREDICATES[parent_focus.metric]
                       and f["scope"]["reference_id"] == "ABC-KT-06"
                       and f["scope"]["stage_index"] == plan.stage
                       and [f["scope"]["walk_start"], f["scope"]["walk_finish"]] == parent_focus.places), None)
        if record:
            fid = record["fact_id"]
            return {"mode": "rag", "answer_kind": "reviewed_guidance", "warnings": [],
                    "evidence": [c for c in release.chunks if c["fact_id"] == fid],
                    "answer": f"The recorded {LABELS[parent_focus.metric]} was for the walk from {parent_focus.places[0]} to {parent_focus.places[1]}. [{fid}]",
                    "trail_focus": parent_focus.model_dump(), "retrieval": {"mode": "previous measurement direction"}}
    if (plan and plan.active_key() == "siwai" and plan.stage == 6 and parent_focus
            and parent_focus.metric in {"moving", "elapsed"}
            and re.search(r"pick.?up|lift booking|meet .*driver|book .*jeep|driver|ride back", text)
            and re.search(r"time|minute|when|booking|promise|guarantee|book|appoint", text)
            and not any(k != "siwai" for k in matching_routes(text))):
        fid = f"KT-D6-{'E' if parent_focus.metric == 'elapsed' else 'M'}"
        timing = next((c for c in release.chunks if c["fact_id"] == fid), None)
        if timing:
            return {"mode": "rag", "answer_kind": "reviewed_guidance", "warnings": [], "evidence": [timing],
                    "answer": f"The Bamboo to Siwai figure is a duration observed on one walk. [{timing['fact_id']}] "
                              "It cannot set your own arrival or pickup time. Confirm the meeting place and time with your driver or operator.",
                    "trail_focus": parent_focus.model_dump(), "retrieval": {"mode": "turn-specific timing and booking scope"}}
    if reference not in {None, "ABC-KT-06"} or OTHER_TOPIC.search(re.sub(r"\bdownhill (?=day|stage|leg)", "", text)):
        return None
    if re.search(
        r"all (?:six |the )?(?:stages|days)|whole (?:trek|trip)|entire (?:trek|trip)|net (?:gain|ascent|change)",
        text,
    ):
        return None
    named_routes = matching_routes(text)
    if any(k != "siwai" for k in named_routes) or (
        plan and plan.active_key() != "siwai" and not re.search(r"keitreks|siwai", text)
    ):
        return None

    names = requested_metrics(text)
    last = parent_focus.metric if parent_focus else None
    break_check = BREAK_CHECK.search(text)
    absolute = last == "gain" and re.search(
        r"(?:is|was) that (?:the |our )?(?:altitude|elevation|height) (?:at|above)", text
    )
    if absolute:
        names = ["gain"]
    elif break_check and last:
        names = [last]
    elif break_check:
        names = ["moving", "elapsed"]
    if MINUTES.search(text) and not names:
        names = [last] if last in {"moving", "elapsed"} else ["moving", "elapsed"]
    pause_definition = re.search(r"which (?:clock|time|reading|timer|duration)|which one", text) and re.search(r"lunch|pause|break|stop", text)
    if pause_definition:
        names = ["elapsed", "moving"]
    if not names:
        return None

    pair = directed_stage(text)
    places = (
        tuple("annapurna base camp" if p == "abc" else p for p in pair)
        if pair
        else tuple(p.casefold() for p in focus.places)
    )
    if (not pair and not requested_stage(text, plan) and (pause_definition or CLOCK_EXPLANATION.search(text))
            and set(names) <= {"moving", "elapsed"} and not break_check
            and (not parent_focus or not parent_focus.metric or "mean" in text)):
        # Both definitions come from the scope notes on a single pair of published clocks.
        ids = {f["fact_id"] for f in release.facts if f["scope"]["stage_index"] == 1
               and f["predicate"] in {PREDICATES[n] for n in names}
               and f["scope"]["reference_id"] == "ABC-KT-06"}
        records = [c for c in release.chunks if c["fact_id"] in ids]
        if len(records) == len(names):
            statements = {
                "moving": "Moving time counts the time the tracker classifies as movement. Stops are excluded.",
                "elapsed": "Elapsed time runs from the first recorded GPS point to the last, including stops and breaks.",
            }
            by_predicate = {f["predicate"]: f["fact_id"] for f in release.facts if f["fact_id"] in ids}
            return {"mode": "rag", "answer_kind": "reviewed_guidance", "warnings": [],
                    "trail_focus": focus.model_dump(), "evidence": records,
                    "retrieval": {"mode": "recorded clock definitions"},
                    "answer": " ".join(f"{statements[n]} [{by_predicate[PREDICATES[n]]}]" for n in names)}
    # "On the way back from B to A" already names the return direction.
    if pair and re.search(r"reverse of|opposite of|in reverse\b|backwards\b", text):
        places = places[::-1]
    elif (
        not pair
        and REVERSE.search(text)
        and parent_focus
        and places == tuple(p.casefold() for p in parent_focus.places)
    ):
        places = places[::-1]

    stages = {
        f["scope"]["stage_index"]: (f["scope"]["walk_start"], f["scope"]["walk_finish"])
        for f in release.facts
        if f["predicate"] == "moving_time" and f["scope"]["reference_id"] == "ABC-KT-06"
    }
    day = requested_stage(text, plan)
    # A named day overrides inherited places; a user-supplied pair must agree with it.
    if (
        day in stages
        and not pair
        and not re.search(
            r"\b(?:from|between|to) (?:deurali|abc|annapurna|bamboo|chhomrong|siwai|mbc)", text
        )
    ):
        places = tuple(p.casefold() for p in stages[day])
        if REVERSE.search(text):
            places = places[::-1]
    if len(places) == 3 and " via " in text:
        for stage_id, ends in stages.items():
            walk = RECORDS["siwai"]["days"][stage_id - 1]["walk"]
            via = (
                (walk or "")
                .partition(" via ")[2]
                .casefold()
                .replace("machhapuchhre", "machhapuchhare")
            )
            if places == (ends[0].casefold(), via, ends[1].casefold()):
                places = (places[0], places[-1])
                break
    if len(places) != 2 or places[0] == places[1]:
        return None
    stage = next(
        (i for i, ends in stages.items() if tuple(p.casefold() for p in ends) == places), None
    )
    place_names = {
        place.casefold(): place for pair_names in stages.values() for place in pair_names
    }
    start, finish = (place_names.get(p, p.title()) for p in places)
    context = (
        plan.model_copy() if plan and plan.active_key() == "siwai" else PlanContext(keys=["siwai"])
    )
    context.stage = stage
    result = {
        "mode": "rag",
        "answer_kind": "stage_measurement",
        "warnings": [],
        "evidence": [],
        "retrieval": {"mode": "reviewed stage, direction and measurement"},
        "variant_context": context.model_dump(),
        "trail_focus": focus.model_copy(
            update={
                "route": "Annapurna Base Camp",
                "reference": "ABC-KT-06",
                "places": [start, finish],
                "metric": None,
            }
        ).model_dump(),
    }
    if day is not None and stage != day:
        result["answer"] = (
            f"The named day and endpoints do not match the recorded KeiTreks stage. Should I use day {day} or {start} to {finish}?"
        )
        return result

    facts = {
        f["predicate"]: f
        for f in release.facts
        if f["scope"]["reference_id"] == "ABC-KT-06"
        and f["scope"]["walk_start"] == start
        and f["scope"]["walk_finish"] == finish
        and f["scope"]["stage_index"] == stage
        and stage is not None
    }
    lines, used = [], []
    for name in names:
        fact = facts.get(PREDICATES[name])
        if not fact:
            lines.append(
                f"I have no verified {LABELS[name]} figure for {start} to {finish} in that direction."
            )
            continue
        fid = fact["fact_id"]
        used.append(fid)
        value = fact["value"]
        if name == "gain":
            lines.append(
                f"KeiTreks’ {start} to {finish} stage gains about {value['number']:,} metres cumulatively. [{fid}]"
            )
            if absolute or break_check:
                lines.append(
                    "That measures uphill travel over the stage, not the altitude at camp or the time spent walking."
                )
        else:
            label = (
                "moving time" if name == "moving" else "door-to-door elapsed time, including stops"
            )
            h, m = divmod(value["number"], 60)
            display = f"{value['number']} minutes" if MINUTES.search(text) else f"{h} hours and {m} minutes"
            lines.append(
                f"On the recorded {start} to {finish} stage, {label} was {display}. [{fid}]"
            )
            if break_check and name == "moving":
                lines.append("This counts time classified as moving; stops are excluded.")
    if (
        {"moving", "elapsed"}.issubset(names)
        and all(PREDICATES[k] in facts for k in ("moving", "elapsed"))
        and re.search(r"gap|difference|how much longer", text)
    ):
        m, e = (facts[PREDICATES[k]] for k in ("moving", "elapsed"))
        lines.append(
            f"The difference is {e['value']['number'] - m['value']['number']} minutes. [{m['fact_id']}, {e['fact_id']}]"
        )
    result["answer"] = " ".join(lines)
    result["evidence"] = [c for c in release.chunks if c["fact_id"] in used]
    result["trail_focus"]["metric"] = names[0] if len(names) == 1 and used else None
    if len(lines) == len(used) == 1 and not break_check and not absolute:
        result["single_observation"] = True
    return result


def matches_observation(answer, fact, question=""):
    """Accept a one-sentence model answer only for the cited direction, number and metric."""
    fid = fact["fact_id"]
    if f"[{fid}]" not in answer:
        return False
    text = answer.lower().replace(f"[{fid.lower()}]", "").replace(",", "").strip(". ")
    if re.search(r"[.!?]\s+|\b(?:not|never|exactly|guaranteed|at least|at most|per hour)\b", text):
        return False
    start, end = (fact["scope"][k].lower() for k in ("walk_start", "walk_finish"))
    text = re.sub(r"\babc\b", "annapurna base camp", text)
    if not (0 <= text.find(start) < text.rfind(end)):
        return False
    text = re.sub(rf"\bday {fact['scope']['stage_index']}\b", "", text)
    number = fact["value"]["number"]
    numbers = [int(n) for n in re.findall(r"\d+", text)]
    if fact["predicate"] == PREDICATES["gain"]:
        return bool(
            numbers == [number]
            and re.search(rf"\b{number}\s*(?:m|metres|meters)\b", text)
            and re.search(r"about|around|roughly|approximately|estimated", text)
            and re.search(
                r"cumulative (?:ascent|elevation gain)|total (?:ascent|elevation gain)|cumulatively",
                text,
            )
            and not re.search(r"descent|downhill|hours?|minutes?|altitude at|above sea level", text)
        )
    hours, minutes = divmod(number, 60)
    right_clock = (
        bool(MOVING.search(text)) and not ELAPSED.search(text)
        if fact["predicate"] == PREDICATES["moving"]
        else bool(ELAPSED.search(text))
        and not MOVING.search(text)
        and bool(re.search(r"includ\w* (?:all |the )?(?:stops|breaks|rests)", text))
    )
    if MINUTES.search(question.casefold()):
        return bool(right_clock and numbers == [number] and re.search(rf"\b{number}\s*(?:minutes?|mins?)\b", text))
    return bool(
        right_clock
        and numbers == [hours, minutes]
        and re.search(
            rf"\b{hours}\s*(?:hours?|hrs?|h)\s*(?:and\s*)?{minutes}\s*(?:minutes?|mins?|m)\b", text
        )
    )
