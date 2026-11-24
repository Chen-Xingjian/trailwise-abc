"""Small, source-backed answers for preparation topics that commonly follow a route plan."""

import re

from app.packing import packing_answer
from app.planning import DAY_NUMBERS, budget_answer, personal_walking_days

PACK = re.compile(r"\b(?:pack(?:ing)?|gear|equipment|bring|carry)\b", re.I)
PREP = re.compile(r"\b(?:physical(?:ly)?|train(?:ing)?|fitness|practi[cs]e|conditioning)\b", re.I)
RATINGS = re.compile(r"rating|temperature|degree|minus|sub.zero|[-−]\s*\d", re.I)

TRAINING_REQUEST = re.compile(
    r"\bhow (?:should|can|do|could) (?:i|we) (?:train|prepare physically|get ready physically|"
    r"practi[cs]e|get in shape|build (?:up )?(?:(?:my|our) )?(?:stamina|endurance))\b|"
    r"\bwhat (?:can|should) (?:i|we) do to (?:train|prepare physically|get in shape)\b|"
    r"\bwhat (?:kind of |sort of )?training (?:would|do) you (?:suggest|recommend)\b|"
    r"\b(?:how|what) about (?:training|preparing physically|getting in shape)\b",
    re.I,
)


PRACTICE = re.compile(
    r"\b(?:practice|training|rehearsal|training hikes?|trained|practised)\b", re.I
)
CONTACT = re.compile(
    r"\b(?:someone at home|staying behind|staying home|flatmate|roommate|partner|family|parent|sister|brother|friend|emergency contact)\b",
    re.I,
)


def practice_question(text):
    return PRACTICE.search(text) and re.search(
        r"compar|ready|readiness|prepar|didn.t|missing|buffer|extra time|lift|cable car|gondola|how .*stack up|more like|match|mirror|replicate|simulate",
        text,
        re.I,
    )


def training_comparison(question, release, reference):
    facts = {f["fact_id"]: f for f in release.facts if f["scope"]["reference_id"] == "ABC-KT-06"}
    if "F03" not in facts:
        return None
    ids = ["F03"]
    parts = []
    text = re.sub(r"\babc\b", "annapurna base camp", question.lower())
    if reference == "ABC-KT-06" or re.search(r"\b(?:keitreks|siwai)\b", text):
        days = personal_walking_days(question)
        if days is not None and "K07" in facts:
            ids.append("K07")
            parts.append(budget_answer(days, "requested", facts["K07"], None))
        field = (
            "approximate_cumulative_descent"
            if re.search(r"descen|downhill|cable car|gondola", text)
            else "approximate_cumulative_ascent"
        )
        for fid, fact in facts.items():
            if fact["predicate"] != field:
                continue
            scope = fact["scope"]
            movement = rf"\b{re.escape(scope['walk_start'].lower())}\s+(?:to|towards?|→)\s+{re.escape(scope['walk_finish'].lower())}\b"
            if re.search(movement, text):
                parts.append(f"{fact['statement_en']} [{fid}]")
                ids.append(fid)
                break
    parts.append(
        f"{facts['F03']['statement_en']} [F03] Matching the hours or having spare days alone does not establish readiness."
    )
    return {
        "answer_kind": "reviewed_guidance",
        "answer": " ".join(parts),
        "evidence": [c for c in release.chunks if c["fact_id"] in ids],
        "retrieval": {"mode": "reviewed preparation and matching stage records"},
    }


def reviewed_guidance(question, release, reference):
    if reference not in {None, "ABC-KT-06"}:
        return None
    text = question.casefold().split(" (location:")[0].split(" (trail section:")[0]
    load = cumulative_training(text, release, reference)
    if load:
        return load
    if re.search(
        r"\b(?:prescribe|dosage|medication|injur\w*|symptom\w*|pregnan\w*|pain|asthma)\b", text
    ):
        return None
    ids = []
    mixed = PACK.search(text) and PREP.search(text) and re.search(r"\b(?:and|both|also)\b", text)
    solo = bool(
        re.search(r"\bsolo\b|(?:go|going|trek|walk|hike|travel|walking|hiking|trekking) alone", text) and re.search(r"safe|suitable|can i|should i", text)
    )
    water = re.search(
        r"untreated|refill|treat(?:ing|ed|ment)? water|water (?:filter|treatment|purif)", text
    )
    food = re.search(r"food|snack|lunch", text)
    exposure = re.search(r"eyes|eye protection|sunglasses|sunburn|exposed skin", text)
    shelter = re.search(r"shelter", text) and re.search(r"first.aid|medical|emergency kit", text)
    split = contact_question(text) and re.search(
        r"split|separate|different routes|one .*other", text
    )
    if shelter:
        ids.append("G12")
    elif food and exposure:
        ids.extend(["G10", "G11"])
    elif re.search(r"porter|rental", text) and re.search(
        r"allowance|luggage|baggage|booking|advance arrangements", text
    ):
        ids.append("G09")
    elif contact_question(text):
        ids.append("F05")
    elif re.search(r"altitude|high elevation", text) and re.search(
        r"fitness|athlet|runner|running|pace|quicker|fast(?:er)?|stairs?|endurance|in shape|workout|stamina", text
    ):
        ids.append("F04")
    elif (
        water
        and re.search(r"water|drink|bottle|hydration", text)
        and re.search(r"carry|bring|before|prepare|work out|sort out|never|first time", text)
    ):
        ids.append("G04")
    elif (
        re.search(r"traction|microspikes|ice grips", text)
        and re.search(r"above|beyond|upper", text)
        and "deurali" in question.lower()
    ):
        if re.search(r"winter|december|january|february", text):
            ids.append("S03")
        ids.append("G07")
    elif practice_question(text) and not re.search(
        r"\b(?:packing|gear|equipment|how (?:should|do) (?:we|i) pack)\b", text
    ):
        return training_comparison(question, release, reference)
    elif CONTACT.search(text) and re.search(
        r"leave|message|tell|share|agree|overdue|late back|return time|check.in", text
    ):
        ids.append("F05")
    elif re.search(r"\b(?:headlamp|head torch|light|lighting)\b", text) and re.search(
        r"batter|backup power", text
    ):
        ids.append("G01")
        if food:
            ids.append("G11")
    elif mixed:
        ids.extend(["G02", "G05", "G01", "G04", "F03"])
    elif "sleeping bag" in text and RATINGS.search(text):
        ids.append("G08")
    elif (
        re.search(r"altitude (?:illness|sickness)|mountain sickness|\bams\b", text)
        and re.search(r"protect|prevent|immune|avoid", text)
        and re.search(r"\bfit(?:ness)?\b|stair|run(?:ning)?|athlet|previous trip", text)
    ):
        ids.append("F04")
    elif TRAINING_REQUEST.search(text):
        ids.append("F03")
    elif re.search(r"\b(?:winter|monsoon)\b", text) and re.search(
        r"weather|typical|season|climate|snow|rain|icy", text
    ):
        if "monsoon" in text:
            ids.append("S02")
        if "winter" in text and "deurali" in question.lower():
            ids.append("S03")
    elif solo:
        ids.append("F05")
    elif (
        re.search(r"pick.?up", text)
        and re.search(r"guarantee|confirm|certain", text)
        and (reference == "ABC-KT-06" or "siwai" in question.lower())
    ):
        ids.append("KT-D6-TRACK-FINISH")
    if not ids:
        return None
    facts = {r["fact_id"]: r for r in release.facts}
    chunks = {r["fact_id"]: r for r in release.chunks}
    if not all(fid in facts and fid in chunks for fid in ids):
        return None
    groups = []
    for fid in ids:
        fact = facts[fid]
        statement = fact["statement_en"]
        if fid == "F05" and split:
            statement = "Give the home contact each person's route and expected return separately, and agree what to do if either person is overdue."
        if fid == "G01" and "G11" in ids:
            statement += " Keep the spares accessible in your day bag so you can restore the light on the trail."
        if fid == "G09":
            statement += " The guide gives no universal allowance."
        if fid == "G12" and shelter:
            statement += " First aid is for treating minor injuries; the shelter gives temporary protection from the elements. Extra medical supplies do not provide that cover."
        if fid == "F05" and solo:
            statement = (
                "I cannot establish whether going solo is safe for you on this itinerary. "
                + statement
            )
        if fid in {"G08", "F04", "S03", "KT-D6-TRACK-FINISH"} and not (
            fid == "S03" and "G07" in ids
        ):
            statement += (
                " "
                + {
                    "G08": "The reviewed guide does not specify a sleeping bag temperature rating.",
                    "F04": "This fact cannot establish an individual's risk.",
                    "S03": "Check a recent local report for actual conditions.",
                    "KT-D6-TRACK-FINISH": "Vehicle stops and passenger pickup there remain unverified.",
                }[fid]
            )
        groups.append(f"{statement} [{fid}]")
        if (
            fid == "G04"
            and water
            and re.search(r"never|new to|first time|unfamiliar|no experience", text)
        ):
            groups.append(
                "To put that plan into practice before leaving, learn how to use your chosen treatment method according to its instructions."
            )
    answer = "\n".join("- " + line for line in groups) if mixed else " ".join(groups)
    return {
        "answer": answer,
        "evidence": [chunks[fid] for fid in ids],
        "answer_kind": "reviewed_guidance",
        "retrieval": {"mode": "reviewed topic records"},
    }


def add_packing_clause(live, question, release, reference):
    """Attach a checklist only for an explicitly requested, independently answerable clause."""
    for clause in re.split(r"\s+(?:and|also)\s+|[?;]", question, flags=re.I):
        if not PACK.search(clause):
            continue
        gear = packing_answer(clause.strip(), release, reference)
        if gear:
            live["answer"] += "\n\n" + gear["answer"]
            present = {c["fact_id"] for c in live.get("evidence", [])}
            live["evidence"].extend(c for c in gear["evidence"] if c["fact_id"] not in present)
            break


def contact_question(text):
    return re.search(
        r"housemate|home contact|person at home|someone at home|emergency contact|check.in|person .*staying behind",
        text,
    ) and re.search(r"return|overdue|worry|late|when to act|check.in|agree", text)


def cumulative_training(text, release, reference):
    if not (reference == "ABC-KT-06" or re.search(r"siwai|keitreks", text)):
        return None
    if not (
        re.search(r"prep|train|practi[cs]", text)
        and re.search(r"subtract|cancel|net|difference|both .*totals", text)
    ):
        return None
    m = re.search(r"\bday[ -](\d+|" + "|".join(DAY_NUMBERS[1:]) + r")\b", text)
    if not m or re.search(r"reverse|opposite direction", text):
        return None
    day = int(m[1]) if m[1].isdecimal() else DAY_NUMBERS.index(m[1])
    matches = {
        f["predicate"]: f
        for f in release.facts
        if f["scope"]["reference_id"] == "ABC-KT-06" and f["scope"]["stage_index"] == day
    }
    gain, loss = (matches.get("approximate_cumulative_" + k) for k in ("ascent", "descent"))
    prep = next((f for f in release.facts if f["fact_id"] == "F03"), None)
    if not (gain and loss and prep):
        return None
    ids = [f["fact_id"] for f in (gain, loss, prep)]
    a, b = gain["value"]["number"], loss["value"]["number"]
    answer = (
        f"On the KeiTreks stage from {gain['scope']['walk_start']} to {gain['scope']['walk_finish']}, "
        f"you climb about {a:,} m and descend about {b:,} m. [{ids[0]}, {ids[1]}] "
        f"The net change of about {a - b:+,} m hides both efforts. Compare both the climbing and the descending with your recent walks under a similar pack load. [F03]"
    )
    return {
        "answer_kind": "reviewed_guidance",
        "answer": answer,
        "evidence": [c for c in release.chunks if c["fact_id"] in ids],
        "retrieval": {"mode": "same-stage cumulative loads and preparation"},
    }
