"""Replay fictional conversations with the same parent fields as the local chat UI."""

import argparse
import json
import re
from pathlib import Path

import httpx

# id, parent, user message, semantic checks (all must match the user-facing reply).
CASES = [
    ("A1", None, "Can you plan my Annapurna Base Camp trek from Siwai?", ["Siwai", "6|six"]),
    ("A2", "A1", "What should I bring for this trip?", ["headlamp", "bedding"]),
    (
        "A3",
        "A2",
        "Are trekking poles compulsory?",
        ["optional|an option|not (?:mandatory|required|compulsory)"],
    ),
    (
        "A4",
        "A2",
        "What about the sleeping bag rating?",
        ["bedding|teahouse", "unverified|not (?:specified|verified)|not .*rating|under review"],
    ),
    (
        "A5",
        "A1",
        "How should I get ready physically for this trek?",
        ["pack|practice", "climb|descen"],
    ),
    (
        "A6",
        "A5",
        "Does being fit protect me from altitude illness?",
        ["does not protect|doesn't protect|not .*protect"],
    ),
    (
        "A7",
        "A1",
        "What about both packing and physical preparation?",
        ["rain shell|headlamp", "practice|training walks"],
    ),
    ("B1", None, "I have five walking days. Which ABC route would suit me?", ["Jhinu", "5|five"]),
    ("B2", "B1", "Show me day 4.", ["ABC → Sinuwa"]),
    ("B3", "B2", "What should I pack for this trip?", ["headlamp"]),
    ("B4", "B3", "Remind me what happens on day 4?", ["ABC → Sinuwa"]),
    (
        "B5",
        "B2",
        "How long did that descent take on the published itinerary?",
        ["6–8|7–8|6.to.8|7.to.8"],
    ),
    ("B6", "B1", "Actually make that four walking days.", ["4|four", "shorter|more time"]),
    ("B7", "B1", "What if I pick Ghandruk instead?", ["Ghandruk", "7 days|seven days", "5|five"]),
    ("B8", "B7", "Show me day 2.", ["Ghandruk → Chhomrong"]),
    ("B9", "B1", "Show me the day-by-day itinerary.", ["Day 5", "Jhinu Danda"]),
    ("C1", None, "How far is the Annapurna Base Camp trek?", ["Ghandruk", "Poon Hill"]),
    ("C2", "C1", "From Nayapul/Birethanti", ["90–95", "Nayapul"]),
    (
        "C3",
        "C2",
        "Can I do that in five days including travel?",
        ["7 days", "shorter|change trailheads"],
    ),
    ("C4", "C3", "What about EBC instead?", ["only.*Annapurna|outside|not cover"]),
    ("C5", "C4", "Can you show its daily stages?", ["Everest|EBC|outside|which route"]),
    ("D1", None, "What's the forecast for Deurali tomorrow?", ["Deurali"]),
    ("D2", "D1", "What about the day after tomorrow?", ["Deurali"]),
    ("D3", "D1", "What about a packing list?", ["headlamp", "rain shell"]),
    ("D4", "D1", "Is the trail open there now?", ["access.*unverified|passage.*unverified"]),
    (
        "D5",
        "D1",
        "What's the weather typically like in winter above Deurali?",
        ["winter", "ice|snow"],
    ),
    ("E1", None, "Show me the daily itinerary for the Poon Hill option.", ["Ghorepani", "Day 8"]),
    ("E2", "E1", "How far is this route?", ["100\\+"]),
    ("E3", "E1", "Where do we walk on day 3?", ["Tadapani → Chhomrong"]),
    ("E4", "E3", "What's the forecast there tomorrow?", ["Chhomrong|which forecast point"]),
    ("F1", None, "Can you plan my ABC trek from Siwai?", ["Siwai"]),
    ("F2", "F1", "What's the exact total walking distance?", ["unverified", "Siwai"]),
    (
        "F3",
        "F1",
        "Is pickup at the bus stop guaranteed?",
        ["unverified|not .*confirm|cannot .*confirm|not guaranteed|not .*verified"],
    ),
]


PARAPHRASES = [
    ("P1", None, "Compare ABC options for five walking days.", ["Jhinu", "5|five"]),
    ("P2", "P1", "Switch to the Poon Hill version instead.", ["Poon Hill", "8 days|eight days"]),
    ("P3", "P2", "Walk me through day 2.", ["Poon Hill → Tadapani"]),
    ("P4", "P3", "What gear should I bring?", ["headlamp", "rain shell"]),
    ("P5", "P4", "And on day 6?", ["Deurali → ABC"]),
    ("P6", None, "Can you plan my ABC trek from Siwai?", ["Siwai"]),
    ("P7", "P6", "How should I pack and train for this hike?", ["rain shell|headlamp", "practice"]),
    (
        "P8",
        "P6",
        "What's the forecast at ABC tomorrow and what should I bring?",
        ["forecast|unavailable", "headlamp|rain shell"],
    ),
    (
        "P9",
        "P6",
        "Can I go alone safely?",
        ["unverified|cannot|can.t|not .*assess|not .*determine|not .*confirm"],
    ),
    ("P10", "P6", "Do I need a minus-ten sleeping bag?", ["bedding", "rating"]),
    (
        "P11",
        "P1",
        "Correction: I have seven calendar days, including two days for flights.",
        ["flight|travel", "Pokhara"],
    ),
    (
        "P12",
        "P3",
        "Can I get a forecast for Tadapani tomorrow?",
        ["which forecast point|unavailable|no .*forecast"],
    ),
]


TRANSFER_CASES = [
    ("T1", None, "I have five walking days. Which route can I take?", ["Jhinu"]),
    ("T2", "T1", "Let's go with the Ghandruk version.", ["Ghandruk", "7 days"]),
    ("T3", "T2", "Where will I be on day 3?", ["Chhomrong → Dovan"]),
    ("T4", "T3", "What should I carry on this hike?", ["headlamp", "rain shell"]),
    ("T5", "T4", "How long is that stage?", ["hours|measurement|unverified"]),
    ("T6", "T1", "How far is the Siwai route?", ["65–70"]),
    (
        "T7",
        "T6",
        "List the daily itinerary for this version.",
        ["Siwai → Chhomrong", "Bamboo → Siwai"],
    ),
    ("T8", None, "What is tomorrow's forecast at ABC?", ["Annapurna Base Camp"]),
    ("T9", "T8", "How about training for the trek?", ["practice|climb|descent"]),
    ("T10", "T1", "Switch to Everest Base Camp.", ["only|outside"]),
    ("T11", "T10", "And how far is that one?", ["EBC|EVEREST|outside"]),
    (
        "T12",
        "T1",
        "Could you compare how long the Ghandruk and Poon Hill options take?",
        ["Ghandruk", "Poon Hill", "7 days", "8 days"],
    ),
]


def run(destination, cases=CASES, *, assess=None):
    turns = {}
    with httpx.Client(base_url="http://127.0.0.1:8765", timeout=90) as client:
        for key, parent, question, checks in cases:
            prev = turns.get(parent, {})
            request = dict(
                question=question,
                mode="rag",
                offer_live_checks=True,
                top_k=3,
                trail_focus=prev.get("trail_focus"),
                chat_context=prev.get("chat_context"),
                prior_planning_question=prev.get("planning_question"),
                variant_context=prev.get("variant_context"),
                distance_followup=prev.get("answer_kind") == "route_distance",
                planning_followup=prev.get("answer_kind") in {"clarification", "itinerary_budget"},
            )
            response = client.post("/api/ask", json=request)
            response.raise_for_status()
            r = response.json()
            turns[key] = r
            row = dict(
                id=key,
                parent=parent,
                question=question,
                checks=checks,
                text_checks_pass=all(re.search(p, r["answer"], re.I | re.S) for p in checks),
                answer=r["answer"],
                kind=r["answer_kind"],
                facts=[c["fact_id"] for c in r.get("evidence", [])],
                itineraries=[s["label"] for s in r.get("itinerary_sources", [])],
                distance_guide=r.get("distance_guide"),
                itinerary_sources=r.get("itinerary_sources", []),
                focus=r.get("trail_focus"),
                plan=r.get("variant_context"),
                live={
                    k: r.get("live", {}).get(k)
                    for k in ("status", "point", "section", "local_date", "checked_at_utc")
                }
                if r.get("live")
                else None,
            )
            passed = row["text_checks_pass"]
            if assess is not None:
                del row["text_checks_pass"], row["checks"]
                row["failed_checks"] = assess(row)
                passed = not row["failed_checks"]
            destination.write(json.dumps(row, ensure_ascii=False) + "\n")
            destination.flush()
            print(key, passed, row["kind"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--paraphrases", action="store_true")
    parser.add_argument("--transfer", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    with args.output.open("x") as output:
        run(
            output,
            CASES + PARAPHRASES + TRANSFER_CASES
            if args.all
            else TRANSFER_CASES
            if args.transfer
            else PARAPHRASES
            if args.paraphrases
            else CASES,
        )
