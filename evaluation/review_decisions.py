"""Development scenarios for interpreting evidence, trip budgets and personal preparation."""

import argparse
from pathlib import Path

from compare_chat_branches import run

CASES = [
    (
        "D01",
        None,
        "Can I finish the whole Siwai trek on an eight-day holiday including the bus both ways?",
        ["walk", "travel|transfer"],
    ),
    (
        "D02",
        "D01",
        "Four full days are left for hiking. My return date is fixed. What do you suggest?",
        ["2 days short", "shorter"],
    ),
    (
        "D03",
        None,
        "What does the February climate grid say about precipitation at Deurali, and how does its elevation compare?",
        ["61.5 mm", "14.7 km", "189 m below"],
    ),
    (
        "D04",
        None,
        "I downloaded a weather forecast for my ABC trip. How do I tell if it applies?",
        ["point|location", "elevation|altitude", "valid|hours", "walk|stage"],
    ),
    (
        "D05",
        "D04",
        "It covers Pokhara on 6 April at noon. We'll hike Deurali to MBC the following morning. Is it suitable?",
        ["Pokhara", "Deurali", "morning", "elevation|altitude"],
    ),
    (
        "D06",
        None,
        "A forwarded bridge closure notice for our ABC trip has no signature. Does it apply to people walking across next week?",
        ["issuer|issued", "section|bridge", "pedestrian|on foot", "valid"],
    ),
    (
        "D07",
        None,
        "My rehearsal walk took as long as the trek stage, but I used a gondola downhill. How should I compare them?",
        ["pack", "climb", "descen"],
    ),
    (
        "D08",
        None,
        "My roommate is staying home. What trip details should we agree on in case I'm late back?",
        ["itinerary", "return", "overdue"],
    ),
    (
        "D09",
        None,
        "I have eight walking days after travel for the KeiTreks trek. My training was all uphill. Is that buffer enough preparation for the descent from ABC to Bamboo?",
        ["2 days? in reserve", "2,000", "pack", "descen"],
    ),
    (
        "D10",
        None,
        "For winter above Deurali, how would I decide whether to take traction on the trek?",
        ["snow or ice|snow and ice", "local reports", "consider"],
    ),
    (
        "D11",
        None,
        "A September photo of the bridge is being shared for our October crossing on the ABC trek. Can we rely on that for pedestrian access?",
        ["October", "issuer|issued", "section|bridge", "pedestrian|on foot", "valid"],
    ),
    (
        "D12",
        None,
        "I'll refill my bottle on the trail and have never used a water filter. What should I sort out before the trek?",
        ["container", "untreated", "practi[cs]e|learn|familiar"],
    ),
    (
        "D13",
        None,
        "For April at ABC, tell me the historical monthly precipitation and how the trail elevation compares with the grid.",
        ["April", "grid", "above"],
    ),
    (
        "D14",
        None,
        "Does my running fitness prevent altitude sickness?",
        ["not protect", "individual"],
    ),
    (
        "D15",
        None,
        "Which light belongs in my hiking kit, and what backup batteries should go with it?",
        ["headlamp", "spare batteries"],
    ),
    (
        "D16",
        None,
        "We are walking the route in reverse from Bamboo to ABC. Does my downhill practice establish I'm ready for that climb?",
        ["pack", "climb", "descen"],
    ),
]
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with args.output.open("x") as output:
        run(output, CASES)
