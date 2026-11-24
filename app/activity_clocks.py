"""Interpret the traveller's own activity readings independently of publisher logs."""
import re

CLOCK = r"\b(\d{1,2}):([0-5]\d)\s*(am|pm)?\b"
DURATION = r"(?:(\d+)\s*(?:hours?|hrs?|h)\s*(?:and\s*)?(?:(\d+)\s*(?:minutes?|mins?|m)?\b)?|(\d+)\s*(?:minutes?|mins?)\b|(\d+):([0-5]\d)\b)"
METRICS = {"moving": r"moving(?: time)?|active(?: time)?", "elapsed": r"elapsed(?: time)?|total time"}


def labelled(text, label):
    # Try the value preceding its label before looking after the label.
    for pattern in (rf"{DURATION}\s*(?:of\s+)?(?:{label})\b",
                    rf"\b(?:{label})\s*(?:was|is|of|=|:)?\s*{DURATION}"):
        if match := re.search(pattern, text):
            hours, mins, mins_only, h_colon, m_colon = match.groups()
            return int(hours or h_colon or 0) * 60 + int(mins or mins_only or m_colon or 0)
    return None


def clock_minutes(match):
    h, m, suffix = match.groups()
    hour = int(h)
    if suffix:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if suffix == "pm" else 0)
    return hour * 60 + int(m) if hour < 24 else None


def activity_answer(question, previous=None):
    text = question.casefold().replace("’", "'")
    # Itinerary times supplied as transport constraints are not stopwatch readings.
    if re.search(r"flight|airport|five.day plan|train departs|bus leaves", text):
        return None
    if not re.search(r"moving|elapsed|stationary|paused|break|lunch|rest stop|both clocks|on foot|active time", text):
        return None
    values = {k: labelled(text, label) for k, label in METRICS.items()}
    moving, elapsed = values["moving"], values["elapsed"]
    prior = previous.personal_clock if previous else None
    if prior and moving is None and elapsed is None and re.search(
        r"again|my (?:own )?(?:readings|times|walk|tracker|activity)|remind|out of that", text
    ) and not re.search(r"keitreks|recorded stage|published|\bfrom .+ to\b", text) and not re.search(r"\d", text):
        elapsed, moving = prior
    if moving is None or elapsed is None:
        clocks = list(re.finditer(CLOCK, text))
        if len(clocks) != 2 or not re.search(r"start|set off|left|finish|arriv|record|walked from|watch ran", text):
            if (elapsed is not None or moving is not None) and re.search(r"my |our |myself|my watch", text):
                missing = "elapsed time" if elapsed is None else "moving time or total stopped time"
                return {"mode": "rag", "answer_kind": "activity_calculation", "evidence": [], "warnings": [],
                        "retrieval": {"mode": "user readings"}, "answer": f"What was your {missing}? That is needed to separate movement and stops."}
            return None
        if not re.search(r"break|lunch|pause|stationary|rest stop|both clocks|moving time", text):
            return None
        start, finish = map(clock_minutes, clocks)
        if start is None or finish is None:
            return None
        elapsed = finish - start
        if elapsed < 0 and re.search(r"overnight|next day|midnight", text):
            elapsed += 1440
        duration = r"(\d+)[ -]*(?:minutes?|mins?)"
        reason = r"(?:lunch|meal|break|pause|stop|rest)(?:s|ed)?"
        pauses = re.findall(rf"{duration}\s*(?:for\s+|at\s+)?(?:a |the )?(?:photo |water )?{reason}\b|"
                            rf"\b{reason}\s*(?:for|of|lasted|was)?\s*{duration}", text)
        stopped = sum(int(a or b) for a, b in pauses)
        zero = re.search(r"no (?:breaks|stops|pauses)|without stopping", text)
        moving = elapsed - stopped if pauses or zero else None
    if elapsed < 0 or (moving is not None and not 0 <= moving <= elapsed):
        answer = "Those readings do not agree for one walking day. Could you confirm the start, finish and total time stopped?"
    else:
        hours, minutes = divmod(elapsed, 60)
        answer = f"Use elapsed time for the whole outing: {elapsed} minutes ({hours} h {minutes:02d})."
        if moving is None:
            answer += " How many minutes in total did you stop? That determines moving time."
        else:
            answer += f" Moving time was {moving} minutes, with {elapsed - moving} minutes stationary."
    return {"mode": "rag", "answer_kind": "activity_calculation", "answer": answer, "warnings": [],
            "personal_clock": (elapsed, moving) if moving is not None and 0 <= moving <= elapsed else None,
            "evidence": [], "retrieval": {"mode": "calculated from user readings"}}
