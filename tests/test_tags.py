from datetime import datetime, timedelta

from api.extensions import db
from api.models import Server, Tag


def test_tag_summary_groups_categorized_tags(client, app):
    with app.app_context():
        db.session.add(Tag(name="role:dns"))
        db.session.add(Tag(name="env:prod"))
        db.session.add(Tag(name="legacy"))
        db.session.add(Server(
            name="dns-alpha",
            tags=["role:dns", "env:prod", "legacy"],
            last_heartbeat=datetime.utcnow(),
        ))
        db.session.add(Server(
            name="dns-beta",
            tags=["role:dns"],
            last_heartbeat=datetime.utcnow() - timedelta(minutes=10),
        ))
        db.session.commit()

    resp = client.get("/api/tags/summary")
    assert resp.status_code == 200
    groups = {group["category"]: group for group in resp.get_json()}

    assert groups["role"]["total_servers"] == 2
    assert groups["role"]["online"] == 1
    assert groups["role"]["offline"] == 1
    assert groups["role"]["tags"][0]["name"] == "role:dns"
    assert groups["role"]["tags"][0]["value"] == "dns"

    assert groups["env"]["total_servers"] == 1
    assert groups["other"]["tags"][0]["name"] == "legacy"
    assert groups["other"]["tags"][0]["categorized"] is False


def test_tag_summary_includes_empty_registered_tags(client, app):
    with app.app_context():
        db.session.add(Tag(name="role:docker"))
        db.session.commit()

    resp = client.get("/api/tags/summary")
    assert resp.status_code == 200
    [group] = resp.get_json()
    assert group["category"] == "role"
    assert group["total_servers"] == 0
    assert group["tags"][0]["servers"] == []
