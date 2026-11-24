"""Classify user-stated walking availability without doing calendar arithmetic."""

import re

from app.retrieval import trip_budget_question

QUESTIONS = {
    "ASK_WINDOW": "After allowing for travel both ways, when can you start walking at the trailhead and when must you finish there? Approximate dates and times, or the parts of days available for hiking, are enough.",
    "ASK_START": "After your inbound transfer, when can you actually start walking at the trailhead?",
    "ASK_FINISH": "When must you finish walking at the trailhead to make your return transfer?",
}

DATE = r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tomorrow|day\s+\d+|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d+|\d+\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*|\d{1,4}[-/]\d{1,2}(?:[-/]\d{1,4})?)\b"
TIME = r"\b(?:\d{1,2}:\d{2}|\d{1,2}\s*(?:am|pm)|morning|afternoon|evening|noon|midday|midnight|dawn|dusk)\b"
NET_DAYS = r"\b(?:i|we)\s+(?:have|have got|can use)\s+(?:only\s+|exactly\s+)?(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:full\s+)?(?:walking|hiking|trekking)\s+days?\b"
START_WALK = r"\b(?:start|begin)\s+(?:walking|hiking|trekking)\b"
END_WALK = r"\b(?:finish|stop|end)\s+(?:walking|hiking|trekking)\b"


def _initial_step(question: str, endpoints: set[str], *, check_window: bool = False) -> str | None:
    text = question.casefold().replace("’", "'")
    personal_plan = re.search(r"\b(?:plan|fit|complete|finish|prepare|feasible|realistic)\b", text)
    full_route = re.search(r"\b(?:trek|hike|itinerary|full route|whole route)\b", text)
    budget = re.search(r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)[ -]+(?:walking |hiking )?days?\b", text)
    if not check_window and not trip_budget_question(question) and not (personal_plan and full_route and budget):
        return None
    named_places = [re.escape(place.casefold()) for place in endpoints if place]
    location = r"\b(?:" + "|".join([r"trail\s?head", *named_places]) + r")\b"
    start = finish = False
    for clause in re.split(r"[!?;\n.]|\b(?:and|but)\b", text):
        if re.search(r"\b(?:unknown|unsure|unconfirmed|unbooked|maybe|might|if|not|don't|can't)\b", clause):
            continue
        if re.search(NET_DAYS, clause) and not re.search(r"\binclud(?:e|es|ing)\b", clause):
            return "PLAN"
        if re.search(r"\b(?:i|we) can (?:walk|hike|trek)\b", clause) and len(re.findall(DATE, clause)) >= 2:
            return "PLAN"
        if not (re.search(DATE, clause) and re.search(TIME, clause)):
            continue
        # A clock time at an airport or city alone is not a trailhead boundary.
        at_endpoint = re.search(location, clause) or (start and re.search(r"\b(?:back )?there\b", clause))
        if re.search(START_WALK, clause):
            start = True
        if re.search(END_WALK, clause):
            finish = True
        if at_endpoint and not re.search(r"\b(?:airport|flight|city)\b", clause):
            if re.search(r"\b(?:arriv\w*|reach\w*|drop\w*|start|begin)\b", clause):
                start = True
            if re.search(r"\b(?:leav\w*|depart\w*|pick\w*|finish|back by)\b", clause):
                finish = True
    if start and finish:
        return "PLAN"
    if start:
        return "ASK_FINISH"
    return "ASK_START" if finish else "ASK_WINDOW"


DAY_NUMBERS = "zero one two three four five six seven eight nine ten eleven twelve".split()
NUMBER = r"(?:\d+(?:\.\d+)?|" + "|".join(DAY_NUMBERS) + ")"
DAY_COUNT = re.compile(rf"\b({NUMBER})[\s-]+(?:(?:full|available|usable|actual|calendar|walking|hiking|trekking|whole)[\s-]+)*days?\b", re.I)


def day_number(token: str) -> float:
    return DAY_NUMBERS.index(token.lower()) if token.lower() in DAY_NUMBERS else float(token)


NET_ALLOCATION = re.compile(
    rf"\b{NUMBER}\s+(?:(?:full|complete|net)\s+)?(?:"
    r"(?:walking|hiking|trekking)\s+days?|days?\s+on\s+foot|"
    r"days?\s+(?:(?:are\s+)?(?:reserved|set aside|available|left|remaining)|remain)\s+"
    r"(?:just\s+|only\s+)?for\s+(?:walking|hiking|trekking)|days?\s+"
    r"(?:just\s+|only\s+)?for\s+(?:walking|hiking|trekking))\b"
)
UNAVAILABLE = re.compile(
    r"\b(?:can(?:not|'t)|unable to)\s+(?:even\s+)?(?:estimate|confirm|give|provide|say|tell)\b"
    r"|\b(?:no idea|don't know|do not know|neither\b[^.!?;]{0,35}\b(?:booked|confirmed|settled))\b"
)
SCHEDULE = re.compile(r"\b(?:time[s]?|window|when|transfer[s]?|pickup[s]?|bookings?|how long|how much time)\b")


def planning_step(question: str, endpoints: set[str]) -> str | None:
    """Consume an availability update from the existing newline-delimited UI."""
    original = _initial_step(question, endpoints)
    history, separator, latest = question.strip().rpartition("\n")
    if not separator:
        return original
    previous = _initial_step(history, endpoints)
    if previous is None and not (
        re.search(r"\b(?:plan|fit|full|whole|itinerary)\b", history, re.I)
        and re.search(r"\b(?:trip|trek|walk|abc|holiday|trailhead)\b", history, re.I)
    ):
        return original

    latest = latest.casefold().replace("’", "'")
    start, finish = previous == "ASK_FINISH", previous == "ASK_START"
    trailhead = r"\b(?:" + "|".join([r"trail\s?head", *(re.escape(p.casefold()) for p in endpoints if p)]) + r")\b"
    at_trailhead = start or finish
    unavailable = False
    for match in re.finditer(r"([^.!?;\n]+)([.!?;]|$)", latest):
        sentence = match[1].strip()
        if match[2] == "?" or re.search(r"\b(?:if|maybe|might|possibly|suppose)\b", sentence):
            continue
        if UNAVAILABLE.search(sentence) and SCHEDULE.search(sentence) and not re.search(
            r"\b(?:price|cost|fare|fee|weight)\b", sentence
        ):
            unavailable = True
        if not re.search(r"\b(?:including|includes?|not|cannot|can't|don't|requires?|itinerary takes)\b", sentence):
            personal = re.search(r"\b(?:have|gives?|leaves?|reserved|set aside|available|allocated)\b", sentence)
            if NET_ALLOCATION.fullmatch(sentence) or (personal and NET_ALLOCATION.search(sentence)):
                return "PLAN"
        for clause in re.split(r"\s+(?:and|but|then)\s+|;", sentence):
            if re.search(r"\b(?:airport|flight|station|hotel)\b", clause):
                at_trailhead = False
                continue
            if re.search(r"\b(?:unknown|unconfirmed|not|can't|cannot|no idea)\b", clause):
                continue
            named = bool(re.search(trailhead, clause))
            related = named or (at_trailhead and re.search(r"\bthere\b", clause))
            at_trailhead = at_trailhead or named
            if not (related and re.search(DATE, clause) and re.search(TIME, clause)):
                continue
            start |= bool(re.search(r"\b(?:gets? (?:us|me) to|drops?|arriv\w*|reach|set (?:out|off)|start|begin)\b", clause))
            finish |= bool(re.search(r"\b(?:back|return|finish|pick(?:s|up)?|collect\w*|meet)\b", clause))
    if start and finish:
        return "PLAN"
    if unavailable:
        return "CONDITIONAL"
    return original


def personal_walking_days(question: str) -> float | None:
    """Read an explicit personal allocation in the latest turn, never a calendar span."""
    latest = question.strip().rpartition("\n")[2].casefold().replace("’", "'")
    if re.search(r"\b(?:includes?|including|counts?)\b[^.!?;]{0,45}\b(?:travel|transfers?|transport|driving|bus)\b", latest):
        return None
    values = set()
    for match in re.finditer(r"(.+?)([!?;]|\.(?!\d)|$)", latest):
        sentence = match[1].strip()
        if match[2] == "?" or re.search(
            r"\b(?:if|maybe|might|could|perhaps|suppose|about|around|approximately|"
            r"between|at least|at most|up to|used to|not sure|don't know|no longer)\b", sentence
        ):
            continue
        for allocation in NET_ALLOCATION.finditer(sentence):
            prefix = sentence[:allocation.start()].strip()
            personal = re.search(
                r"\b(?:(?:we|i|our (?:group|party))\s+(?:(?:actually|now)\s+)?"
                r"(?:have(?: got)?|has|can use)|(?:leaves?|gives?)\s+(?:us|me))"
                r"(?:\s+(?:only|just|exactly))?$", prefix
            )
            if re.fullmatch(r"(?:after|excluding) (?:the )?(?:transfers?|travel|drives?)[, ]*", prefix):
                personal = True
            if not personal and prefix:
                continue
            tail = sentence[allocation.end():].strip()
            # An unqualified, short reply can itself be an allocation. A guide's
            # count or a past trip is not a statement of the group's availability.
            if tail and not re.match(r"^(?:[, ]*(?:alone\b|after\b|once\b|excluding\b|available\b|left\b|in total\b|,?\s*and (?:my|our) (?:dates|leave)\b))", tail):
                continue
            token = allocation[0].split()[0]
            values.add(day_number(token))
    return values.pop() if len(values) == 1 else None


DEFAULT_WALKING_DAYS = 5


def itinerary_request(question: str, endpoints: set[str], followup: bool) -> tuple[str, float | str] | None:
    """Read a requested itinerary length separately from the published route duration."""
    text = question.strip().casefold().replace("’", "'").replace("–", "-")
    latest = text.rpartition("\n")[2]
    trip = re.search(r"\b(?:abc|annapurna base camp|siwai)\b", text)
    planning = re.search(r"\b(?:plan(?:ning)?|itinerar(?:y|ies)|suggest a route|day.by.day|schedule)\b", text)
    # A short reply can change the assumption without restating the route.
    update = followup and re.fullmatch(
        rf"(?:actually[, ]+)?(?:make it |change it to |use |i have |we have |i can walk for )?"
        rf"{NUMBER}[ -]+(?:full |net )?(?:walking |hiking |trekking )?days?"
        r"(?: for (?:walking|hiking)| on foot| after transfers| including (?:travel|transfers))?[.!? ]*", latest)
    generic = re.fullmatch(
        rf"(?:(?:can|could) you |please )?(?:help me |give me |suggest |show me )?"
        rf"(?:plan |build |make )?(?:(?:my|our|a|an|the|me) )?(?:{NUMBER}[ -]day )?"
        r"(?:trek|hike|trip|itinerary)(?: plan| itinerary)?[?.! ]*", text)
    factual = re.search(r"\b(?:recorded|published|usually|normally|typically|reference|guarantee|"
                        r"which (?:places|villages|stops)|where (?:did|do)|what (?:did|does))\b", text)
    window_reply = (followup and "?" not in latest and re.search(rf"{DATE}|{TIME}", latest)
                    and re.search(r"\b(?:trailhead|walking|transfers?|arrival|flight)\b", latest))
    if followup and trip and personal_walking_days(question) is not None:
        update = True
    if factual or not (update or window_reply or generic or (trip and planning)):
        return None
    if re.search(r"\b(?:training|weather|gear|packing|equipment|permit|distance|cost|"
                 r"gokyo|everest|poon hill|nayapul|ghandruk|bedding|poles|altitude|fitness|food|water|snow|rain|solo)\b", text):
        return None
    if re.search(r"\b(?:how (?:many|long)|how much|what (?:is|was) the duration|"
                 r"how (?:do|should) (?:i|we) (?:train|prepare))\b", text):
        return None
    # Ask about actual walking availability if the user supplied calendar or travel
    # constraints. Do not replace a partial window with the default.
    explicit_net = personal_walking_days(question)
    if explicit_net is not None:
        return ("requested", explicit_net)
    timing_text = re.sub(r"\b(?:excluding|not including|after subtracting) (?:the |both )?"
                         r"(?:round.trip |return )?(?:transfers?|transport|travel)(?: time)?\b", "", latest)
    constrained = re.search(
        rf"{DATE}|{TIME}|\b(?:transfers?|flights?|driv(?:e|ing)|transport|travel|holiday|vacation|"
        r"weekends?|weeks?|nights?|hours?|leave|arriv\w*|depart\w*|between|maybe|might|not sure|"
        r"cannot|can.t|don.t have|do not have|unable|at most|up to|no more than|january|february|march|april|may(?! i\b)|june|"
        r"july|august|september|october|november|december)\b", timing_text)
    if constrained:
        step = planning_step(question, endpoints) or _initial_step(latest, endpoints, check_window=True)
        return ("window", step)
    if re.search(rf"\b{NUMBER}\s*(?:-|or|to)\s*{NUMBER}\b", latest):
        return ("window", "ASK_WINDOW")
    counts = DAY_COUNT.findall(latest)
    if len(counts) == 1:
        if re.search(r"\b(?:in total|total|off work|available overall)\b", latest):
            return ("window", "ASK_WINDOW")
        return ("requested", day_number(counts[0]))
    if counts or re.search(r"\d|\b(?:day|days|months?|fortnight|years?)\b", re.sub(r"day.by.day", "", latest)):
        return None
    return ("default", DEFAULT_WALKING_DAYS)


def budget_answer(days: float, origin: str, count_fact: dict, stages: dict | None) -> str:
    required = count_fact["value"]["number"]
    count_id = count_fact["fact_id"]
    unit = "day" if days == 1 else "days"
    lead = (f"For this example, I’ll use {days:g} walking {unit}, excluding travel to and from Siwai."
            if origin == "default" else f"Your plan allows {days:g} walking {unit} from Siwai.")
    if days < required:
        gap = required - days
        comparison = (f"{lead} The published round trip takes {required:g} walking days, "
                f"so this budget is {gap:g} {'day' if gap == 1 else 'days'} short [{count_id}]. "
                "Allow the extra walking time for the full trek, or choose a shorter objective with a verified turnaround and return if your dates are fixed.")
    else:
        surplus = days - required
        relation = (f"That matches the published {required:g} walking days" if not surplus
                  else f"The published route uses {required:g} walking days, leaving {surplus:g} "
                       f"{'day' if surplus == 1 else 'days'} in reserve")
        comparison = f"{lead} {relation} [{count_id}]."
    parts = [comparison]
    if stages and len(stages["value"]["places"]) == required + 1:
        stops = stages["value"]["places"][1:]
        parts.append(f"Stops on the {required:g}-day reference: " + " → ".join(stops) + f" [{stages['fact_id']}].")
    if origin == "default":
        parts.append("You can change the budget, for example to six walking days.")
    return "\n\n".join(parts)


def checked_window_summary(question: str, draft: str, facts: list[dict]) -> str | None:
    """Fall back to user statements and retrieved facts if a draft assigns a day budget."""
    route_counts = {f["value"]["number"] for f in facts if f["predicate"] == "walking_day_count"}
    for sentence in re.split(r"[.!?\n]", draft):
        counts = DAY_COUNT.findall(sentence)
        if not counts:
            continue
        personal = re.search(r"\b(?:you|your|available|usable|left|remaining|leaves you)\b", sentence, re.I)
        if personal or any(day_number(n) not in route_counts for n in counts):
            break
    else:
        return None

    net_days = personal_walking_days(question)
    count_facts = [f for f in facts if f["predicate"] == "walking_day_count"]
    if (net_days is not None and len(count_facts) == 1 and
            count_facts[0]["fact_id"] == "K07" and
            count_facts[0].get("scope", {}).get("reference_id") == "ABC-KT-06"):
        count_fact = count_facts[0]
        required = count_fact["value"]["number"]
        unit = "day" if net_days == 1 else "days"
        parts = [f"You have {net_days:g} {unit} available for walking. "
                 f'{count_fact["statement_en"]} [{count_fact["fact_id"]}]']
        if net_days < required:
            parts.append("The full itinerary will not fit as recorded. A shorter objective would need its own route evidence.")
        else:
            relation = "matches" if net_days == required else "exceeds"
            parts.append(f"Your time budget {relation} the recorded number of walking days. "
                         "That alone cannot guarantee that your group will finish all the stages.")
        wants_preparation = re.search(r"\b(?:prepare|preparation|training|practise|practice|ready|readiness|workload)\b", question, re.I)
        if net_days >= required or wants_preparation:
            for fact in facts:
                if (fact["predicate"] == "practice_walk_comparison" and
                        fact.get("scope", {}).get("reference_id") == count_fact["scope"]["reference_id"]):
                    parts.append(f'{fact["statement_en"]} [{fact["fact_id"]}]')
        return "\n\n".join(parts)

    timing = [
        part.strip() for part in re.split(r"[!?;\n.]|,\s*(?=can (?:I|we)\b)", question)
        if (re.search(DATE, part, re.I) and re.search(TIME, part, re.I))
        or re.search(NET_DAYS, part, re.I) or re.search(r"\bcan (?:hike|walk|trek)\b", part, re.I)
    ]
    parts = ["Your stated walking availability: “" + " ".join(timing) + "”." if timing else
             "Use the walking window you supplied as the outer limits of your trip."]
    budget = re.search(rf"\b(?:I|we) have (?:only )?({NUMBER}) days? (?:in total|total|including travel)\b", question, re.I)
    if budget and route_counts and day_number(budget[1]) < min(route_counts):
        parts.append("Your total trip is already shorter than the reviewed walking itinerary. To follow the full reference, allow a longer trip.")
    for fact in facts:
        if fact["predicate"] in {"walking_day_count", "walking_boundary", "practice_walk_comparison"}:
            parts.append(f'{fact["statement_en"]} [{fact["fact_id"]}]')
    parts.append("A shorter itinerary would need its own route evidence.")
    return "\n\n".join(parts)
