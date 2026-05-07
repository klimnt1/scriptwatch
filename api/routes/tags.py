from flask import Blueprint, jsonify, request
from api.extensions import db
from api.models import Tag, Server

tags_bp = Blueprint("tags", __name__)


def parse_tag(name):
    name = (name or "").strip()
    if ":" not in name:
        return {"name": name, "category": "other", "value": name, "categorized": False}
    category, value = [part.strip() for part in name.split(":", 1)]
    if not category or not value:
        return {"name": name, "category": "other", "value": name, "categorized": False}
    return {"name": name, "category": category, "value": value, "categorized": True}


@tags_bp.get("/")
def list_tags():
    return jsonify([t.name for t in Tag.query.order_by(Tag.name).all()])


@tags_bp.get("/summary")
def tag_summary():
    all_tags = [t.name for t in Tag.query.order_by(Tag.name).all()]
    servers = Server.query.filter(Server.pending_uninstall == False).order_by(Server.name).all()  # noqa: E712
    groups = {}

    for name in all_tags:
        parsed = parse_tag(name)
        category = parsed["category"]
        groups.setdefault(category, {
            "category": category,
            "tags": [],
            "online": 0,
            "offline": 0,
            "total_servers": 0,
        })

    for name in all_tags:
        parsed = parse_tag(name)
        matching_servers = [s for s in servers if name in (s.tags or [])]
        online = sum(1 for s in matching_servers if s.is_online)
        offline = len(matching_servers) - online
        group = groups[parsed["category"]]
        group["online"] += online
        group["offline"] += offline
        group["total_servers"] += len(matching_servers)
        group["tags"].append({
            **parsed,
            "online": online,
            "offline": offline,
            "total_servers": len(matching_servers),
            "servers": [s.name for s in matching_servers],
        })

    return jsonify([
        {
            **group,
            "tags": sorted(group["tags"], key=lambda t: (t["value"], t["name"])),
        }
        for group in sorted(groups.values(), key=lambda g: g["category"])
    ])


@tags_bp.post("/")
def create_tag():
    name = (request.get_json(force=True).get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    if Tag.query.filter_by(name=name).first():
        return jsonify({"error": "tag already exists"}), 409
    tag = Tag(name=name)
    db.session.add(tag)
    db.session.commit()
    return jsonify({"name": tag.name}), 201


@tags_bp.put("/<string:name>")
def rename_tag(name):
    tag = Tag.query.filter_by(name=name).first()
    if not tag:
        return jsonify({"error": "not found"}), 404
    new_name = (request.get_json(force=True).get("name") or "").strip()
    if not new_name:
        return jsonify({"error": "name required"}), 400
    if new_name != name and Tag.query.filter_by(name=new_name).first():
        return jsonify({"error": "tag already exists"}), 409
    for server in Server.query.all():
        if server.tags and name in server.tags:
            server.tags = [new_name if t == name else t for t in server.tags]
    tag.name = new_name
    db.session.commit()
    return jsonify({"name": tag.name})


@tags_bp.delete("/<string:name>")
def delete_tag(name):
    tag = Tag.query.filter_by(name=name).first()
    if not tag:
        return jsonify({"error": "not found"}), 404
    for server in Server.query.all():
        if server.tags and name in server.tags:
            server.tags = [t for t in server.tags if t != name]
    db.session.delete(tag)
    db.session.commit()
    return jsonify({"ok": True})
