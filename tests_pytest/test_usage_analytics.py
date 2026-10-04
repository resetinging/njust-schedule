# -*- coding: utf-8 -*-
import os

os.environ.setdefault(
    "SQLALCHEMY_DATABASE_URI",
    "sqlite:///:memory:",
)

from wxcloudrun import app, db
from wxcloudrun.admin import _issue_admin_token
from wxcloudrun.model import UsageEvent, UsageSlotUserDaily, UsageUserDaily


def _payload(visitor_id="visitor-test"):
    return {
        "consent": True,
        "visitor_id": visitor_id,
        "events": [
            {
                "id": "e1",
                "name": "app_open",
                "session_id": "session-1",
                "page": "schedule",
                "platform": "",
                "properties": {},
            },
            {
                "id": "e2",
                "name": "page_view",
                "session_id": "session-1",
                "page": "schedule",
                "platform": "",
                "properties": {},
            },
            {
                "id": "e3",
                "name": "slot_visible",
                "session_id": "session-1",
                "page": "schedule",
                "slot_id": "slot-schedule-bottom",
                "ad_type": "native",
                "visible_ms": 1200,
                "platform": "",
                "properties": {"visible_ms": 1200},
            },
        ],
    }


def test_usage_events_aggregate_and_dedupe():
    c = app.test_client()
    first = c.post("/api/analytics/events", json=_payload("visitor-aggregate"))
    second = c.post("/api/analytics/events", json=_payload("visitor-aggregate"))

    assert first.status_code == 200
    assert first.get_json()["accepted"] == 3
    assert second.status_code == 200
    assert second.get_json()["duplicates"] == 3

    with app.app_context():
        assert UsageEvent.query.count() == 3
        assert UsageEvent.query.filter(
            UsageEvent.analytics_id == "visitor-aggregate"
        ).count() == 0
        user_day = UsageUserDaily.query.one()
        assert user_day.open_count == 1
        assert user_day.page_views == 1
        assert user_day.event_count == 3
        slot_day = UsageSlotUserDaily.query.one()
        assert slot_day.visible_count == 1
        assert slot_day.visible_ms == 1200


def test_usage_requires_consent_and_rejects_unknown_events():
    c = app.test_client()
    no_consent = c.post("/api/analytics/events", json={
        "visitor_id": "visitor-no-consent",
        "events": _payload()["events"],
    })
    assert no_consent.status_code == 400

    invalid = _payload("visitor-invalid")
    invalid["events"][0]["name"] = "unknown_event"
    response = c.post("/api/analytics/events", json=invalid)
    assert response.status_code == 200
    assert response.get_json()["rejected"] == 1


def test_admin_analytics_report_reads_daily_rollups():
    c = app.test_client()
    c.post("/api/analytics/events", json=_payload("visitor-admin"))
    token = _issue_admin_token()
    response = c.get(
        "/api/admin/analytics?days=7",
        headers={"X-Admin-Token": token},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["overview"]["dau"] >= 1
    assert payload["pages"]
    assert payload["slots"]
