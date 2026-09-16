#!/usr/bin/env python3
"""Run inside a disposable kind web pod, after migrations and preflight pass."""

import json
import os
import time
import urllib.request
import uuid


def main():
    if os.environ.get("POSTHOG_RELEASE_SMOKE") != "disposable-kind":
        raise SystemExit("Refusing to create smoke data outside an explicitly disposable kind run")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    import django

    django.setup()
    from posthog.clickhouse.client import sync_execute
    from posthog.models import Organization, Team

    event_id = str(uuid.uuid4())
    organization = Organization.objects.create(name=f"release-smoke-{event_id}")
    team = Team.objects.create(organization=organization, name="Release smoke")
    payload = {
        "api_key": team.api_token,
        "event": "release_smoke",
        "uuid": event_id,
        "properties": {"distinct_id": event_id, "$process_person_profile": False},
    }
    request = urllib.request.Request(
        "http://posthog-capture:3000/i/v0/e/",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"Capture rejected smoke event: {response.status}")

    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        rows = sync_execute(
            "SELECT count() FROM events WHERE team_id = %(team_id)s AND uuid = %(uuid)s",
            {"team_id": team.pk, "uuid": event_id},
        )
        if rows[0][0] > 0:
            print(f"PASS: event {event_id} traversed capture, Kafka, ingestion and ClickHouse")
            return
        time.sleep(5)
    raise SystemExit(f"Event {event_id} never reached ClickHouse within 300 seconds")


if __name__ == "__main__":
    main()
