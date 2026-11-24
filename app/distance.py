"""Read an operator's route-specific planning ranges separately from the fact index."""

import re
import threading
import time
from datetime import UTC, datetime
from html.parser import HTMLParser

import httpx

GUIDE = "https://www.magicalnepal.com/travel-guide/annapurna/annapurna-base-camp-trek-distance/"
TRAILHEADS = {
    "Jhinu Danda": "Jhinu Danda",
    "Siwai": "Siwai",
    "Ghandruk": "Ghandruk",
    "Nayapul": "Nayapul/Birethanti",
}
EXTENSION = "Ghorepani and Poon Hill"
LABELS = {**TRAILHEADS, EXTENSION: EXTENSION}
PLACES = {
    "Jhinu Danda": r"jhinu(?: danda)?",
    "Siwai": "siwai",
    "Ghandruk": "ghandruk",
    "Nayapul": r"nayapul(?:\s*/\s*birethanti)?|birethanti",
    EXTENSION: r"poon hill|ghorepani",
}
PLACE = "(?:" + "|".join(PLACES.values()) + ")"
# Recognise standalone whole-trek questions. Segment, travel and compound requests
# continue through the regular assistant, which preserves the rest of the question.
DISTANCE = re.compile(
    r"\b(distance|mileage|how far|how many (?:km|kilomet(?:er|re)s|miles)|"
    r"how long .*?\b(?:km|miles|kilomet(?:er|re)s))\b",
    re.I,
)
ROUTE_WORDS = set(
    """a about abc actual all an and annapurna approximate approximately are as at
back base both by camp can complete could d days direct distance do does estimated exact far finish for
from full give go hike hiking how i in is it its kei keitreks km kilometres kilometers leave length
long many me mileage miles my of on out overall please reference return returning roughly round roundtrip route
six sixday siwai jhinu danda ghandruk nayapul start starting tell the there this to total track trek
trekking trip two up via walk walking way what whats with would you your
birethanti poon hill ghorepani including include add detour extension compare versus vs or different
options routes approaches versions distances which shortest longest short longer starts ends common main available there typical
end ending finishing exit exiting 6 itinerary that if also adding without excluding""".split()
)


def distance_question(question: str, reference: str | None) -> bool:
    if reference not in {None, "ABC-KT-06"}:
        return False
    text = question.lower().replace("abc-kt-06", "abc").replace("what's", "what is")
    text = re.sub(r"\b(?:six|6)[ -]day\b", "sixday", text)
    if not re.search(r"\b(?:abc|annapurna base camp)\b", text):
        return False
    if not (
        DISTANCE.search(text)
        or re.search(r"\b(?:routes|approaches|versions|route options)\b", text)
    ):
        return False
    if re.search(r"\bone[ -]way\b|\beach way\b", text):
        return False
    if re.search(r"\bfrom (?:the )?(?:abc|annapurna base camp|poon hill|ghorepani)\b", text):
        return False
    if re.search(rf"\bto {PLACE}\b", text) and not re.search(r"\bfrom\b", text):
        return False
    return set(re.findall(r"[a-z]+|\d+", text)) <= ROUTE_WORDS


def distance_followup(question):
    """A short reply to the trailhead question, never a new planning or weather request."""
    return (
        re.fullmatch(
            rf"(?:(?:what|how) about |(?:what if )?i (?:start|go) |starting |via |including )?"
            rf"(?:from |via )?{PLACE}(?: (?:via|and|to) {PLACE})?[?.! ]*",
            question.strip(),
            re.I,
        )
        is not None
    )


def copied_distance_option(question):
    """Read one printed option as a trailhead choice. Its pasted number is not evidence."""
    row = re.fullmatch(
        r"(?:[-*•]\s+)?((?:from|via)\s+[^\n]+?)\s*[-–—]\s*"
        r"(?:\*\*)?(?:usually\s+)?\d+(?:\s*[-–—−]\s*\d+|\+)?\s*km(?:\*\*)?[.!]?",
        question.strip(), re.I,
    )
    if row and distance_followup(row[1]):
        return row[1]
    return None


def selected_trailhead(question):
    """Extract a single menu reply, retaining any actual question for normal routing."""
    if pasted := copied_distance_option(question):
        return pasted
    choice = re.fullmatch(
        r"(?:i(?:'ll| will) (?:take|choose|go with)|i(?:'d| would) (?:like|prefer)|"
        r"let(?:'s| us) (?:take|try|go with)|i (?:choose|pick|prefer))\s+"
        r"(?:the\s+)?(?:one\s+)?(.+?)(?:\s+(?:option|one|route|version))?[.! ]*",
        question.strip().replace("’", "'"), re.I,
    )
    if choice and distance_followup(choice[1]):
        return choice[1]
    return question


class GuideSections(HTMLParser):
    """Extract round-trip estimates from the labelled comparison table or a route section."""

    def __init__(self):
        super().__init__()
        self.tag = ""
        self.parts = []
        self.pending = None
        self.ranges = {}
        self.cells = []
        self.distance_table = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.distance_table = False
        if tag == "tr":
            self.cells = []
        if tag in {"h1", "h2", "h3", "h4", "p", "th", "td"}:
            self.tag = tag
            self.parts = []
            if tag != "p":
                self.pending = None

    def handle_data(self, data):
        if self.tag:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "tr" and len(self.cells) >= 2:
            label, value = self.cells[:2]
            if label == "Starting point":
                self.distance_table = value == "Approx. walking distance to ABC and back"
            elif self.distance_table:
                match = re.fullmatch(r"Usually (\d{1,3})\+ km", value, re.I)
                if label == "Ghorepani + Poon Hill + ABC" and match and int(match[1]) > 0:
                    self.ranges[EXTENSION] = f"usually {match[1]}+ km"
                trailheads = {
                    "Jhinu Danda": "Jhinu Danda",
                    "Siwai/Jhinu area": "Siwai",
                    "Ghandruk": "Ghandruk",
                    "Nayapul/Birethanti area": "Nayapul",
                }
                interval = re.fullmatch(r"About (\d{1,3})[–−-](\d{1,3}) km(?: / .+)?", value)
                if label in trailheads and interval and 0 < int(interval[1]) < int(interval[2]):
                    self.ranges[trailheads[label]] = f"{interval[1]}–{interval[2]} km"
        if tag == "table":
            self.distance_table = False
        if tag != self.tag:
            return
        value = " ".join("".join(self.parts).split())
        if tag in {"th", "td"}:
            self.cells.append(value)
        if tag == "h3":
            self.pending = next(
                (
                    key
                    for key, heading in TRAILHEADS.items()
                    if value == f"{heading} to Annapurna Base Camp Distance"
                ),
                None,
            )
        elif tag == "p" and self.pending:
            match = re.match(
                r"Approximate round-trip walking distance:\s*(?:around )?"
                r"(\d{1,3})\s*[–−-]\s*(\d{1,3})\s*km\b",
                value,
                re.I,
            )
            if match and 0 < int(match[1]) < int(match[2]):
                self.ranges[self.pending] = f"{match[1]}–{match[2]} km"
            self.pending = None
        self.tag = ""


class DistanceGuideCache:
    """Reuse one complete, attributed operator table briefly within this app session."""

    def __init__(self):
        self.lock = threading.Lock()
        self.ranges = {}
        self.fetched_at = None
        self.expires = 0.0

    def read(self, client):
        if client is None:
            return {}, None
        with self.lock:
            if self.ranges and time.monotonic() < self.expires:
                return self.ranges, self.fetched_at
            guide = GuideSections()
            try:
                response = client.get(GUIDE)
                response.raise_for_status()
                guide.feed(response.text)
                guide.close()
            except httpx.HTTPError:
                return {}, None
            checked = datetime.now(UTC).isoformat()
            if set(guide.ranges) == set(LABELS):
                self.ranges = guide.ranges
                self.fetched_at = checked
                self.expires = time.monotonic() + 900
            return guide.ranges, checked


def route_distance(question, release, client, reference=None, cache=None):
    named = [
        name for name, pattern in PLACES.items() if re.search(rf"\b(?:{pattern})\b", question, re.I)
    ]
    skip_extension = bool(
        re.search(r"\b(?:without|excluding) (?:ghorepani|poon hill)\b", question, re.I)
    )
    if skip_extension and EXTENSION in named:
        named.remove(EXTENSION)
    reviewed = bool(
        re.search(r"keitreks|abc-kt-06", question, re.I)
        or ("Siwai" in named and re.search(r"(?:six|6)[ -]day", question, re.I))
        or reference == "ABC-KT-06"
    ) and not any(name != "Siwai" for name in named)
    comparing = bool(re.search(r"\b(compare|versus|vs|or|both)\b", question, re.I))
    combined = len(named) > 1 and not comparing
    examples = named
    if combined:
        examples = [EXTENSION] if EXTENSION in named else []
    if not named:
        examples = ["Siwai"] if reviewed else list(TRAILHEADS if skip_extension else LABELS)
    ranges, checked = (cache or DistanceGuideCache()).read(client)
    available = [name for name in examples if name in ranges]
    paragraphs = []
    if reviewed:
        paragraphs.append(
            "The exact distance of the six-day KeiTreks walk from Siwai and back is still unverified."
        )
    if combined:
        paragraphs.append("I don’t have a verified total for that particular combination of stops.")
    if len(available) == 1:
        name = available[0]
        label = "via " + EXTENSION if name == EXTENSION else "from " + LABELS[name]
        paragraphs.append(
            f"Magical Nepal estimates **{ranges[name]}** for the round trip {label}. "
            "This covers walking only. Road transfers are extra."
        )
    elif available:
        paragraphs.append(
            "Magical Nepal estimates these round-trip walking distances to Annapurna Base Camp. Road transfers are excluded."
        )
        paragraphs.append(
            "\n".join(
                f"- {('Via ' if name == EXTENSION else 'From ')}{LABELS[name]} — **{ranges[name]}**"
                for name in available
            )
        )
    if available and named and not combined:
        missing = [LABELS[name] for name in named if name not in available]
        if missing:
            paragraphs.append(
                "The guide’s estimate could not be verified for " + " and ".join(missing) + "."
            )
    if not available and not combined:
        if reviewed:
            paragraphs.append("The reviewed itinerary covers six walking days.")
        else:
            subject = " and ".join(LABELS[name] for name in named) or "the ABC routes"
            paragraphs.append(
                f"I couldn’t verify a walking-distance estimate for {subject} from the guide."
            )
    if not named and not reviewed:
        paragraphs.append("Where would you like to start walking?")
    elif named and not combined and not reviewed and len(available) == 1:
        paragraphs.append("Your return trail and pickup point can change the total.")
    return {
        "answer": "\n\n".join(paragraphs),
        "answer_kind": "route_distance",
        "mode": "rag",
        "model_id": None,
        "release_id": release.manifest["release_id"],
        "warnings": [],
        "evidence": []
        if available or not reviewed
        else [c for c in release.chunks if c["fact_id"] == "K07"],
        "distance_guide": {
            "title": "Magical Nepal · walking distances by starting point",
            "url": GUIDE,
            "used": bool(available),
            "checked_at_utc": checked,
        },
    }
