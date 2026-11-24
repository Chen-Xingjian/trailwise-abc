import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app import source_watch
from app.config import ROOT
from app.live import notices
from app.release import load_release
from app.source_watch import acknowledge, compare, fingerprint, report_dir, scan, targets_for
from app.trail_updates import (
    MUNICIPAL,
    FieldReport,
    add_local_sources,
    field_observations,
    municipal_notices,
    question_section,
    register_field_report,
)


def test_watch_comparisons_and_dependency_impact():
    release = load_release(ROOT / "data/release")
    release.facts[1]["dependencies"]["required_fact_ids"] = [release.facts[0]["fact_id"]]
    rule = {
        "id": "source",
        "url": "https://example.org",
        "kind": "file",
        "facts": [release.facts[0]["fact_id"]],
        "audit_fingerprint": "a",
    }
    (target,) = targets_for(release, [rule])
    assert release.facts[1]["fact_id"] in target["facts"]
    drift = compare(target, {}, "b", "t1")
    assert drift["comparison"] == "changed"
    failed = compare(target, drift, None, "t2", "timeout")
    assert failed["availability"] == "unavailable" and failed["comparison"] == "changed"
    assert compare(target, failed, "b", "t3")["comparison"] == "changed"
    assert compare(target, failed, "a", "t3")["comparison"] == "matches audit"


def test_reports_persist_skip_and_require_explicit_revision(tmp_path, monkeypatch):
    release = ROOT / "data/release"
    settings = tmp_path / "config"
    settings.mkdir()
    (settings / "abc_source_watch.json").write_text(
        json.dumps(
            [
                dict(
                    id="page",
                    kind="file",
                    url="https://example.org/data",
                    facts=["K07"],
                    audit_fingerprint="accepted",
                )
            ]
        )
    )
    monkeypatch.setattr(source_watch, "ROOT", tmp_path)
    hits = []

    def response(req):
        hits.append(str(req.url))
        return httpx.Response(200, content=b"new value")

    now = datetime.now(UTC) - timedelta(days=2)
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        one = scan(release, tmp_path, now=now, client=client)
        two = scan(release, tmp_path, now=now + timedelta(hours=2), client=client)
        assert one == two and len(hits) == 1 and one["review_fact_ids"] == ["K07"]
        target = one["targets"][0]
        folder = report_dir(release, tmp_path)
        with pytest.raises(ValueError):
            acknowledge(folder, "page", "stale", "Reviewed")
        acknowledge(
            folder,
            "page",
            target["observed"],
            "Reviewed by test assessor; underlying wording unchanged.",
        )
        three = scan(release, tmp_path, now=now + timedelta(days=8), client=client)
        assert three["review_fact_ids"] == [] and len(three["review_history"]) == 1
        assert len(list(folder.glob("2*.json"))) == 3


def test_dynamic_runtime_ignored_but_data_change_detected():
    rows = [
        {"generationtime_ms": 12, "daily": {"time": ["2020-01-01"], "temperature_2m_mean": [15]}}
        for _ in range(3)
    ]

    def signature():
        return fingerprint({"kind": "era5"}, json.dumps(rows).encode())

    original = signature()
    rows[0]["generationtime_ms"] = 1
    assert signature() == original
    rows[0]["daily"]["temperature_2m_mean"][0] = 16
    assert signature() != original


def test_municipal_listing_is_scoped_and_overlap_has_no_clearance(tmp_path):
    html = '<a href="/other">open</a><div id="notices_listing"><a href="/notice/a">पदमार्ग सूचना</a><a href="https://other.org">other</a></div>'

    def response(req):
        return httpx.Response(200, text=html) if str(req.url) == MUNICIPAL else httpx.Response(503)

    now = datetime.now(UTC)
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        result = add_local_sources(notices(client, now), client, now, tmp_path, "Deurali to MBC")
    assert result["status"] == "unavailable" and result["municipal"]["status"] == "listed"
    assert [i["title"] for i in result["municipal"]["items"]] == ["पदमार्ग सूचना"]
    assert result["municipal"]["items"][0]["observed_at"] is None
    assert result["trail_access"] == "unverified" and not result["field_reports"]
    assert question_section("Is Deurali to MBC open today?") == "Deurali to MBC"
    for page, status in [
        ('<div id="notices_listing">No results found</div>', "empty"),
        ("<footer>No results found</footer>", "unavailable"),
    ]:
        with httpx.Client(
            transport=httpx.MockTransport(lambda _, page=page: httpx.Response(200, text=page))
        ) as client:
            assert municipal_notices(client, now)["status"] == status


def test_field_time_validity_selection_and_idempotency(tmp_path):
    values = dict(
        section="Deurali to MBC",
        subject="pedestrians",
        publisher="Test fixture",
        source_url="https://example.org/report",
        observation="Synthetic observation for testing.",
        observed_at="2020-01-01T06:00:00+05:45",
        published_at="2020-01-02T06:00:00+05:45",
        valid_until="2020-01-03T06:00:00+05:45",
    )
    for fields in ({"observed_at": "2020-01-01T06:00:00"}, {"observed_at": "2020-01-04T06:00:00Z"}):
        with pytest.raises(ValueError):
            FieldReport(**{**values, **fields})
    record = FieldReport(**values)
    register_field_report(tmp_path, record)
    register_field_report(tmp_path, record)
    now = datetime.now(UTC)
    rows, invalid = field_observations(tmp_path, "Deurali to MBC", now)
    assert len(rows) == 1 and invalid == 0 and rows[0]["validity"] == "expired"
    assert rows[0]["observed_at"] != rows[0]["published_at"]
    assert not field_observations(tmp_path, "MBC to ABC", now)[0]
    (tmp_path / "corrupt.json").write_text("{}")
    assert field_observations(tmp_path, "ABC corridor", now)[1] == 1
