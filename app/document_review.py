"""Consult monthly grid records and evaluate traveller-supplied weather or access material."""

import calendar
import re

from app.live_chat import PLACES
from app.turn_context import ALIASES


def monthly_answer(question, release, focus, months):
    text = question.casefold()
    if not months or not re.search(
        r"historic|climate|climatolog|era5|monthly (?:rainfall|precipitation|mean)", text
    ):
        return None
    if re.search(r"tomorrow|forecast for|will it", text):
        return None
    names = {
        "chhomrong": "Chhomrong",
        "deurali": "Deurali",
        "abc": "ABC",
        "annapurna base camp": "ABC",
    }
    sites = list(
        dict.fromkeys(names[m.lower()] for m in PLACES.findall(question) if m.lower() in names)
    )
    if not sites and re.search(r"\b(?:the |at )?base camp\b", text):
        sites = ["ABC"]
    if not sites:
        sites = [names[p.lower()] for p in focus.places if p.lower() in names]
    if not sites or len(months) != 1:
        return None
    month = list(calendar.month_name).index(months[0])
    by_id = {
        f["fact_id"]: f
        for f in release.facts
        if f["predicate"] == "historical_monthly_grid_climate"
    }
    ids = [f"S05-{site.upper()}-{month:02d}" for site in sites]
    if not all(i in by_id for i in ids):
        return None
    statements = [by_id[i]["statement_en"] for i in ids]
    answer = " ".join(f"{statement} [{i}]" for statement, i in zip(statements, ids, strict=True))
    if len(ids) == 2:
        metric = (
            ("monthly total precipitation", "mm")
            if re.search(r"rain|precipitation|wetter|drier", text)
            else ("2-m temperature", "°C")
        )
        values = [re.search(metric[0] + r" of ([-−\d.]+) " + metric[1], s) for s in statements]
        periods = [re.search(r"\b(\d{4}[–-]\d{4})\b", s) for s in statements]
        if all(values) and all(periods) and periods[0][1] == periods[1][1]:
            a, b = [float(m[1].replace("−", "-")) for m in values]
            lead = (
                f"{sites[0] if a > b else sites[1]} was higher by {abs(a - b):.1f} {metric[1]}"
                if a != b
                else f"Both sites had the same {metric[0]}"
            )
            answer = (
                f"{lead}. In {months[0]} ({periods[0][1]}), ERA5 mean {metric[0]} was "
                f"{a:g} {metric[1]} near {sites[0]} and {b:g} {metric[1]} near {sites[1]}. [{ids[0]}, {ids[1]}]"
            )
    answer += " These are historical grid averages."
    if re.search(r"overnight|night|minimum|lowest|low\b", text):
        answer += " A monthly mean cannot tell you the minimum temperature on a particular night."
    constraints = {}
    if re.search(
        r"waterproof|warm layer|insulat|rain (?:shell|jacket)|packing", text
    ) and "G02" in {f["fact_id"] for f in release.facts}:
        ids.append("G02")
        answer += (
            " Keep a rain shell and an insulating layer suited to the conditions you expect. [G02]"
        )
        if "S06" in release.scope.get("dynamic_verification_rules", {}):
            constraints["S06"] = release.scope["dynamic_verification_rules"]["S06"]
            answer += " Check a current forecast for your walking point, elevation and hours before deciding what to carry."
    return {
        "answer": answer,
        "mode": "rag",
        "answer_kind": "reviewed_guidance",
        "evidence": [c for c in release.chunks if c["fact_id"] in ids],
        "verification_rules": constraints,
        **({"chat_context": {"climate_fact": ids[0]}} if len(sites) == 1 else {}),
        "warnings": [],
        "retrieval": {"mode": "monthly grid records by site and month"},
    }


def material_answer(question, release, focus, previous):
    rules = release.scope.get("dynamic_verification_rules", {})
    if not rules:
        return None
    text = question.casefold()
    named = [p.casefold() for p in PLACES.findall(question)]
    months = [m for m in list(calendar.month_name)[1:] if re.search(rf"\b{m}\b", text, re.I)]
    ids, rule, follow = [], None, False
    supplied = re.search(
        r"\b(?:saved|downloaded|forwarded|screenshot|screen shot|printout|clipping|old|copied|photo|picture|message says)\b",
        text,
    )
    check = re.search(
        r"relevan|rely|use it|use this|appl(?:y|ies|icable)|suitable|enough|settle|what.*(?:check|need)|tell whether|count on|can (?:i|we)",
        text,
    )
    if re.search(
        r"\b(?:get|fetch|look up|check) (?:a |the )?(?:new|latest|current) (?:forecast|bulletin|notices?)",
        text,
    ):
        return None
    if monthly := monthly_answer(question, release, focus, months):
        return monthly
    if previous and previous.climate_fact and re.search(r"sleeping bag|sleep system|bag rating", text):
        ids = [previous.climate_fact, "G08"]
        chunks = [c for c in release.chunks if c["fact_id"] in ids]
        if len(chunks) == 2:
            return {"mode": "rag", "answer_kind": "reviewed_guidance", "warnings": [], "evidence": chunks,
                    "answer": f"The earlier monthly grid mean does not give the overnight low at your lodge. [{ids[0]}] "
                              "Check the bedding your teahouse provides before choosing a sleeping bag. [G08] "
                              "Those details do not establish an exact temperature rating.",
                    "retrieval": {"mode": "previous climate record and bedding guidance"}}
    rain_probability = re.search(r"chance|probability|percent|likelihood", text) and re.search(r"rain|precipitation", text)
    if rain_probability and re.search(r"month|climat", text) and "S06" in rules:
        return {"mode": "rag", "answer_kind": "reviewed_guidance", "warnings": [], "evidence": [],
                "verification_rules": {"S06": rules["S06"]},
                "answer": "A rain probability describes the chance of precipitation at a place during a forecast period. "
                          "An average monthly precipitation total is an amount: add the precipitation over each whole month, "
                          "then average those totals across years. To check a hiking day, use the forecast for your walking location, elevation and hours.",
                "retrieval": {"mode": "climate interpretation and forecast applicability"}}
    weather_transfer = (re.search(r"forecast|weather app|sunshine|sunny|weather report", text)
                        and re.search(r"higher|lower|valley|another (?:point|place)|different elevation|up the trail", text)
                        and re.search(r"infer|assume|apply|count on|tell me|expect|represent|same|compare", text))
    if weather_transfer and "S06" in rules:
        return {"mode": "rag", "answer_kind": "reviewed_guidance", "warnings": [], "evidence": [],
                "verification_rules": {"S06": rules["S06"]},
                "answer": "A reading at another location or elevation cannot establish conditions on your walk. "
                          "Check a forecast for the point you will reach, at its elevation and covering the full time you expect to be there.",
                "retrieval": {"mode": "forecast applicability"}}
    vehicle_notice = (
        re.search(r"notice|order|restriction|ban", text)
        and re.search(r"truck|freight|vehicle|lorry|lorries", text)
        and re.search(r"footbridge|pedestrian bridge|bridge.*on foot", text)
    )
    if vehicle_notice and "S07" in rules:
        return {
            "answer_kind": "reviewed_guidance",
            "mode": "rag",
            "warnings": [],
            "evidence": [],
            "answer": "If the order restricts vehicles on the road, that provision alone does not establish whether pedestrians can use your footbridge. Check a current notice from the responsible authority for that exact bridge, pedestrian access and your crossing date. Its status remains unconfirmed.",
            "verification_rules": {"S07": rules["S07"]},
            "retrieval": {"mode": "reviewed notice applicability"},
        }
    if (supplied and re.search(r"forecast|outlook|weather", text) and check) or (
        previous
        and previous.reviewing_forecast
        and re.search(
            r"screenshot|it covers|it's for|it is for|forecast (?:was|is) for|printout|valid from",
            text,
        )
        and not re.search(
            r"(?:get|fetch|look up|check) (?:a |the )?(?:new|latest|current) forecast", text
        )
    ):
        rule = "S06"
        if len(set(named)) >= 2 and re.search(r"walk|hik(?:e|ing)|trek", text):
            # Keep the forecast location separate from explicitly described walking endpoints.
            clauses = re.split(r"[.!?;]|\b(?:but|whereas|while)\b", question, flags=re.I)
            src = next(
                (
                    c.strip()
                    for c in clauses
                    if PLACES.search(c)
                    and re.search(r"screenshot|forecast|covers|printout|it(?:'s| is) for", c, re.I)
                ),
                "",
            )
            dst = next(
                (
                    c.strip()
                    for c in clauses
                    if PLACES.search(c)
                    and re.search(r"\b(?:walk|walking|hike|hiking|trek)\b", c, re.I)
                    and c.strip() != src
                ),
                "",
            )
            if (
                src
                and dst
                and {
                    ALIASES.get(p.lower(), p.lower()).lower() for p in PLACES.findall(src)
                }.isdisjoint(ALIASES.get(p.lower(), p.lower()).lower() for p in PLACES.findall(dst))
            ):
                answer = (
                    f"The forecast you describe (“{src}”) is for a different point from your walk "
                    f"(“{dst}”). Use a forecast for the walking section at its elevation, valid throughout your intended hours."
                )
            else:
                answer = "Check whether the forecast point and elevation represent your walking section and whether its validity covers your entire walking window. Different place names alone do not establish that match."
        else:
            follow = True
            answer = "What location, elevation and valid hours does the saved forecast cover, and which section and hours do you intend to walk? Those details let you compare the two."
    elif (
        supplied
        and re.search(r"bridge|crossing|passage|access|closure|closed|block", text)
        and check
    ):
        rule = "S07"
        season = next((f for f in release.facts if f["fact_id"] == "S01"), None)
        answer = "That material alone cannot confirm pedestrian access for your crossing. Check who issued the notice, the exact bridge or trail section, whether it covers pedestrians, and its validity on your crossing date. Look for a current update."
        crossing = re.search(
            r"\b(" + "|".join(list(calendar.month_name)[1:]) + r") crossing\b", question, re.I
        )
        if crossing:
            answer = answer.replace("for your crossing.", f"for your {crossing[1]} crossing.")
        if season and "season" in text:
            answer = season["statement_en"] + " [S01] " + answer
            ids.append("S01")
    else:
        return None
    if rule and rule not in rules:
        return None
    result = {
        "mode": "rag",
        "answer_kind": "reviewed_guidance",
        "answer": answer,
        "evidence": [c for c in release.chunks if c["fact_id"] in ids],
        "warnings": [],
        "retrieval": {"mode": "reviewed source applicability" if rule else "monthly grid record"},
    }
    if rule:
        result["verification_rules"] = {rule: rules[rule]}
    if follow:
        result["chat_context"] = {"reviewing_forecast": True}
    return result
