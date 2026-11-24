"""Answer general packing-list requests from the released, route-scoped gear records."""

import re

# Match the request itself so an individual item or a second question is not
# silently replaced by a general list. Appended subject hints are handled separately.
REQUEST = re.compile(
    r"(?:(?:hey|hi)[, ]+)?(?:please )?(?:(?:what|how) about )?(?:"
    r"what (?:should|needs? to) go (?:in|into) (?:my|our|the) daypacks?|"
    r"(?:any|what) (?:essentials|gear|items) (?:i|we) should (?:pack|bring|carry|take)|"
    r"what (?:do (?:i|we) need to (?:take|carry|bring|pack))|"
    r"what (?:(?:gear|equipment|essentials|items|things|supplies) )?"
    r"(?:(?:should|must|do|would|shall) (?:i|we) (?:need to )?(?:pack|bring|carry|take|need)"
    r"|to (?:bring|pack|carry|take))|"
    r"(?:how (?:should|do) (?:i|we) pack)|"
    r"(?:(?:can|could|would) you )?(?:(?:give|show|make|suggest|recommend) (?:me |us )?)?"
    r"(?:a |an |the |my )?(?:packing (?:list|checklist)|gear (?:list|checklist)|equipment list))"
    r"(?: (?:with (?:me|us)|along))?"
    r"(?: (?:for|on|to) (?:this |that |the |my |our |an? )?"
    r"(?:(?:six.day |6.day )?(?:annapurna base camp|abc|siwai) ?)?"
    r"(?:one|trip|trek|hike|route|itinerary|walk|(?:hiking |trekking |walking )?plan)?(?: from siwai)?)?",
    re.I,
)
GROUPS = {
    "Clothing and footwear": ("G05", "G02", "G10"),
    "In your daypack": ("G01", "G04", "G11", "G12"),
    "Navigation": ("G03",),
    "Before leaving": ("G08", "G06", "G07"),
}


# Supplemental public guidance is attributed separately from the frozen local release.
PACK_RAIN = {
    "fact_id": "NPS-DRY-01",
    "text": "Cover the pack in rain. Inside it, enclose clothes and the sleeping bag in waterproof or plastic bags. Protect electronics in a waterproof case.",
    "source_url": "https://www.nps.gov/locations/alaska/gear.htm",
    "source_title": "US National Park Service · Appropriate Gear",
    "source_locator": "Detailed Gear Checklist · backpack cover, interior bags and electronics case",
    "licence_id": "US-Gov-PD",
    "licence_url": "https://www.nps.gov/aboutus/disclaimer.htm",
    "attribution": "Adapted from US National Park Service guidance for backpacking in Alaska. General packing technique only.",
    "source_updated": "2023-03-30",
    "checked_on": "2026-11-25",
}


def rain_packing(question):
    text = question.casefold()
    contents = re.search(r"\b(?:pack|backpack|rucksack|kit|gear|belongings|contents|electronics|phone|sleeping bag|spare clothes)\b", text)
    moisture = re.search(r"\b(?:dry|drier|soak(?:ed|ing)?|waterproof(?:ing)?|rain(?:cover|proof)?|wet|downpour|pack cover)\b", text)
    if not contents or not moisture or re.search(r"forecast|historical|temperature rating|how cold|how long|is it raining|will it rain", text):
        return None
    if not re.search(r"keep|protect|cover|waterproof|inside|soak|pack.{0,25}(?:dry|wet|rain)|(?:rain|wet).{0,25}(?:gear|pack)", text):
        return None
    answer = "Use a rain cover over your pack and put clothing and your sleeping bag in waterproof or plastic bags inside it."
    if re.search(r"electronics|camera|phone", text):
        answer += " Use a waterproof case for electronics."
    answer += " [NPS-DRY-01]"
    if re.search(r"rating|millimet|\bmm\b|guarantee", text):
        answer += " The guidance gives no waterproof rating or guarantee."
    return {"answer": answer, "answer_kind": "reviewed_guidance", "evidence": [PACK_RAIN],
            "retrieval": {"mode": "supplemental NPS pack-protection guidance"}, "warnings": []}


def is_packing_request(question):
    request = (
        re.sub(
            r"\s*\((?:Location:|Trail section:|Annapurna Base Camp trek\.)[^()]*\)$",
            "",
            question,
            flags=re.I,
        )
        .strip()
        .rstrip("?.! ")
        .strip()
    )
    return REQUEST.fullmatch(request) is not None


def packing_answer(question, release, reference):
    if reference not in {None, "ABC-KT-06"} or not is_packing_request(question):
        return None
    chunks = {c["fact_id"]: c for c in release.chunks if c["reference_id"] == "ABC-KT-06"}
    statements = {
        f["fact_id"]: f["statement_en"]
        for f in release.facts
        if f["scope"]["reference_id"] == "ABC-KT-06"
    }
    # Stage numbers and bedding are qualified to the specific audited itinerary.
    siwai = reference == "ABC-KT-06" or bool(re.search(r"\bsiwai\b", question, re.I))
    evidence, lines = [], []
    daypack_only = bool(re.search(r"\bgo (?:in|into) (?:my|our|the) daypacks?\b", question, re.I))
    for label, ids in GROUPS.items():
        sentences = []
        for fid in ids:
            if fid not in statements or fid not in chunks or (fid in {"G06", "G07"} and not siwai):
                continue
            if daypack_only and fid in {"G05", "G06", "G07", "G08"}:
                continue
            evidence.append(chunks[fid])
            sentences.append(f"{statements[fid]} [{fid}]")
        if sentences:
            lines.append(f"- **{label}** — " + " ".join(sentences))
    if not evidence:
        return None
    lead = (
        "For the Annapurna Base Camp trek from Siwai, pack for long walking days and teahouse nights."
        if siwai
        else "Here are the general packing items in the Annapurna Base Camp guide."
    )
    return {
        "answer_kind": "packing_list",
        "answer": lead + "\n\n" + "\n".join(lines),
        "retrieval": {"mode": "reviewed packing records"},
        "evidence": evidence,
    }
