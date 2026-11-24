"""Local ABC notice discovery and dated field observations."""

import argparse
import json
import os
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.release import canonical_hash

MUNICIPAL = "https://visit.annapurnamunkaski.org/notices/"
NTNC = "https://epermit.ntnc.org.np/support"
LODGES = "https://visit.annapurnamunkaski.org/accomodations/"
Section = Literal["ABC corridor", "Deurali to MBC", "MBC to ABC"]
CONTACTS = [
    {
        "name": "Chhomrong Checkpost / Ghandruk ACAP office",
        "source": NTNC,
        "use": "The NTNC support directory lists the ABC trek under Ghandruk. Ask about current pedestrian restrictions and their validity.",
    },
    {
        "name": "Dream Lodge, Deurali / Fishtail Guest House, MBC",
        "source": LODGES,
        "use": "The municipal accommodation directory lists these endpoint businesses. Ask when someone actually walked the named section and what they observed.",
    },
]


class NoticeListing(HTMLParser):
    """Read only the municipal listing; navigation links repeat the word 'notices'."""

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.found = False
        self.text = []
        self.links = []
        self.href = None
        self.label = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div" and attrs.get("id") == "notices_listing":
            self.found = True
            self.depth = 1
        elif self.depth:
            if tag == "div":
                self.depth += 1
            if tag == "a":
                self.href = attrs.get("href")
                self.label = []

    def handle_endtag(self, tag):
        if self.depth and tag == "a" and self.href:
            url = urljoin(MUNICIPAL, self.href)
            label = " ".join(" ".join(self.label).split())
            if (
                label
                and urlsplit(url).netloc == urlsplit(MUNICIPAL).netloc
                and url.startswith("https://")
            ):
                self.links.append(
                    {"title": label, "url": url, "published_utc": None, "observed_at": None}
                )
            self.href = None
        if self.depth and tag == "div":
            self.depth -= 1

    def handle_data(self, text):
        if self.depth:
            self.text.append(text)
            if self.href:
                self.label.append(text)


def municipal_notices(client, now):
    base = {
        "publisher": "Annapurna Rural Municipality tourism portal",
        "source": MUNICIPAL,
        "checked_at_utc": now.isoformat(),
        "items": [],
        "observed_at": None,
    }
    try:
        response = client.get(MUNICIPAL)
        response.raise_for_status()
        listing = NoticeListing()
        listing.feed(response.text)
        if not listing.found or listing.depth:
            raise ValueError("listing not recognised")
        if listing.links:
            # Keep all languages, including notices whose titles do not identify a trail.
            return {
                **base,
                "status": "listed",
                "items": listing.links,
                "message": "Municipal listing entries. Verify the route, effective dates and pedestrian scope in each original notice.",
            }
        if "no results found" in " ".join(listing.text).lower():
            return {
                **base,
                "status": "empty",
                "message": "The municipality's notice listing shows no entries.",
            }
    except (httpx.HTTPError, ValueError):
        pass
    return {
        **base,
        "status": "unavailable",
        "message": "The municipal notice listing could not be verified.",
    }


class FieldReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section: Section
    subject: Literal["pedestrians", "vehicles", "pack animals"]
    publisher: str = Field(min_length=2, max_length=150)
    source_url: HttpUrl
    observed_at: AwareDatetime
    published_at: AwareDatetime
    valid_until: AwareDatetime | None = None
    observation: str = Field(min_length=5, max_length=700)

    @model_validator(mode="after")
    def chronological(self):
        if self.observed_at > self.published_at or self.published_at > datetime.now(UTC):
            raise ValueError(
                "Observation must precede publication and both must already have occurred."
            )
        if self.valid_until is not None and self.valid_until < self.observed_at:
            raise ValueError("Validity cannot end before the observation.")
        return self


def register_field_report(folder, report):
    data = report.model_dump(mode="json")
    key = canonical_hash(data)
    folder.mkdir(parents=True, exist_ok=True)
    # A hard link publishes a complete record atomically and makes duplicate imports idempotent.
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", dir=folder, delete=False) as tmp:
        name = Path(tmp.name)
        try:
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())
            try:
                os.link(name, folder / (key + ".json"))
            except FileExistsError:
                pass
        finally:
            name.unlink(missing_ok=True)
    return key


def field_observations(folder, section, now):
    found = []
    invalid = 0
    for file in folder.glob("*.json"):
        try:
            record = FieldReport.model_validate_json(file.read_text())
            if file.stem != canonical_hash(record.model_dump(mode="json")):
                raise ValueError("record fingerprint mismatch")
        except (ValueError, OSError):
            invalid += 1
            continue
        if section != "ABC corridor" and record.section != section:
            continue
        item = record.model_dump(mode="json")
        item["validity"] = (
            "end time unspecified"
            if record.valid_until is None
            else "expired"
            if record.valid_until <= now
            else "within stated validity"
        )
        found.append(item)
    return sorted(
        found,
        key=lambda r: datetime.fromisoformat(r["observed_at"].replace("Z", "+00:00")),
        reverse=True,
    ), invalid


def question_section(text):
    mbc = re.search(r"\bmbc\b|machh?apuchh?(?:re|are) base camp", text, re.I)
    if mbc and re.search(r"\bdeurali\b", text, re.I):
        return "Deurali to MBC"
    if mbc and re.search(r"\babc\b|annapurna base camp", text, re.I):
        return "MBC to ABC"
    return "ABC corridor"


def add_local_sources(national, client, now, folder, section, municipal=None):
    if municipal is None:
        municipal = municipal_notices(client, now)
    reports, invalid = field_observations(folder, section, now) if folder is not None else ([], 0)
    result = {
        **national,
        "section": section,
        "municipal": municipal,
        "contacts": CONTACTS,
        "field_reports": reports,
        "invalid_field_reports": invalid,
    }
    result["message"] += " " + municipal["message"]
    if folder is None:
        return result
    result["message"] += (
        f" {len(reports)} dated field observation(s) are listed for {section}."
        if reports
        else f" No reviewed field observation is on file for {section}."
    )
    return result


if __name__ == "__main__":
    from app.config import ROOT

    parser = argparse.ArgumentParser(
        description="File an operator-reviewed public field observation without changing the fact index."
    )
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    print(
        register_field_report(
            ROOT / "runtime/field-reports", FieldReport.model_validate_json(args.report.read_text())
        )
    )
