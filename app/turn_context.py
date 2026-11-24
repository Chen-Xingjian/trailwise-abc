"""Carry the geographic subject of one answer, separate from its factual evidence."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.citations import citation_ids
from app.release import Release

ALIASES = {"abc": "Annapurna Base Camp", "mbc": "Machhapuchhare Base Camp",
           "machhapuchhre base camp": "Machhapuchhare Base Camp"}
OTHER_ROUTE = re.compile(r"\b(?:everest|ebc|gokyo|manaslu|annapurna circuit|ama dablam)\b", re.I)
REVERSE = re.compile(r"\b(?:reverse(?:d)?|opposite direction|other way|way back|return direction)\b", re.I)
DAY = re.compile(r"\bday\s+([1-6])\b", re.I)


class TrailFocus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    route: Literal["Annapurna Base Camp"] | None = None
    reference: str | None = Field(default=None, max_length=80)
    outside_route: str | None = Field(default=None, max_length=40)
    metric: Literal["gain", "moving", "elapsed"] | None = None
    personal_clock: tuple[int, int] | None = None
    places: list[str] = Field(default_factory=list, max_length=3)


class TrailSubjects:
    def __init__(self, release: Release):
        self.refs = set(release.scope["allowed_reference_ids"])
        self.facts = {f["fact_id"]: f for f in release.facts}
        self.stages = {}
        names = {"Tadapani", "Dovan", "Ulleri", "Jhinu Hot Spring", "Pokhara", "Ghandruk", "Jhinu Danda", "Poon Hill", "Ghorepani", "Birethanti", "Nayapul"}
        for fact in release.facts:
            scope = fact["scope"]
            names.update(fact["value"].get("places", []))
            names.update(p for p in (scope["walk_start"], scope["walk_finish"]) if p)
            if fact["predicate"] == "moving_time":
                self.stages[scope["stage_index"]] = [scope["walk_start"], scope["walk_finish"]]
        self.names = {n.casefold(): n for n in names}
        self.names.update(ALIASES)
        self.pattern = re.compile(r"\b(?:" + "|".join(map(re.escape, sorted(self.names, key=len, reverse=True))) + r")\b", re.I)

    def resolve(self, question, previous, selected):
        """Return the new focus and a retrieval question; explicit locations take priority."""
        empty = TrailFocus(reference=selected)
        if other := OTHER_ROUTE.search(question):
            empty.outside_route = other[0]
            return empty, question
        if previous and previous.outside_route and not (self.pattern.search(question) or selected):
            return previous, question
        prior = previous or empty
        valid_names = set(self.names.values())
        prior_places = prior.places if all(p in valid_names for p in prior.places) else []
        # The route name in 'ABC trek from Siwai' is not an extra endpoint.
        geography = re.sub(r"\b(?:ABC|Annapurna Base Camp)[ -]+(?:trek|itinerary|route|hike)\b", "", question, flags=re.I)
        named = [self.names[m[0].casefold()] for m in self.pattern.finditer(geography)]
        places = list(dict.fromkeys(named))
        day = DAY.search(question)
        if not places and day:
            places = self.stages.get(int(day[1]), [])
        if not places and not day:
            places = list(reversed(prior_places)) if REVERSE.search(question) else list(prior_places)
        # A new explicitly named location releases an inferred itinerary filter.
        reference = selected or (prior.reference if prior.reference in self.refs and not named else None)
        annapurna = bool(named or day or reference or prior.route or re.search(
            r"\b(?:abc|annapurna (?:sanctuary|base camp))\b", question, re.I))
        focus = TrailFocus(reference=reference, places=places if len(places) <= 3 else [],
                           route="Annapurna Base Camp" if annapurna else None)
        if not named and not day and not focus.places and prior.route:
            return focus, f"{question.rstrip()} (Annapurna Base Camp trek.)"
        if named or not focus.places:
            return focus, question
        if len(focus.places) == 1:
            return focus, f"{question.rstrip()} (Location: {focus.places[0]}.)"
        if len(focus.places) == 2:
            return focus, f"{question.rstrip()} (Trail section: {' to '.join(focus.places)}.)"
        return focus, question

    def from_answer(self, focus, result):
        used = citation_ids(result["answer"])
        facts = [self.facts[e["fact_id"]] for e in result.get("evidence", [])
                 if e.get("fact_id") in used and e["fact_id"] in self.facts]
        refs = {f["scope"]["reference_id"] for f in facts}
        if not focus.reference and len(refs) == 1:
            focus.reference = refs.pop()
        sections = {(f["scope"]["walk_start"], f["scope"]["walk_finish"]) for f in facts
                    if f["scope"].get("walk_start") and f["scope"].get("walk_finish")
                    and f["scope"]["walk_start"] != f["scope"]["walk_finish"]}
        if not focus.places and len(sections) == 1:
            focus.places = list(sections.pop())
        return focus
