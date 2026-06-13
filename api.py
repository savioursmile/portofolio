"""
Portfolio REST API  —  deploy this on Render (Python web service)
-----------------------------------------------------------------
Environment variables to set in Render:
  API_SECRET        — shared secret, must match the bot's API_SECRET
  WEBHOOK_URL       — your Discord channel webhook (forwarded from the portfolio form)
  DATABASE_PATH     — optional, defaults to data/api.db

Endpoints
  GET    /projects
  POST   /projects           { title, description, tags[], icon, span }
  PATCH  /projects/<id>      any subset of the above fields
  DELETE /projects/<id>

  GET    /donate
  POST   /donate             { name, url, label, icon }
  DELETE /donate/<name>

  POST   /contact            called by the portfolio form (proxies to Discord webhook)
  GET    /submissions        list all contact submissions (secret required)

All mutating routes require header:  X-Secret: <API_SECRET>
"""

import json
import os
import sqlite3
import uuid
import requests
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, jsonify, request, abort

app = Flask(__name__, static_folder=".", static_url_path="")

API_SECRET = os.environ.get("API_SECRET")
if not API_SECRET:
    raise RuntimeError("API_SECRET environment variable is required")

WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
DATABASE_PATH = os.environ.get("DATABASE_PATH", "data/api.db")


# ── Database ──────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    con = sqlite3.connect(DATABASE_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db():
    with get_db() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id          TEXT PRIMARY KEY,
                title       TEXT NOT NULL,
                description TEXT NOT NULL,
                tags        TEXT NOT NULL DEFAULT '[]',
                icon        TEXT NOT NULL DEFAULT '💻',
                span        INTEGER NOT NULL DEFAULT 2,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS donate (
                name        TEXT PRIMARY KEY,
                url         TEXT NOT NULL DEFAULT '',
                label       TEXT NOT NULL DEFAULT '',
                icon        TEXT NOT NULL DEFAULT '🔗'
            );
            CREATE TABLE IF NOT EXISTS submissions (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL DEFAULT '',
                email       TEXT NOT NULL DEFAULT '',
                message     TEXT NOT NULL DEFAULT '',
                timestamp   TEXT NOT NULL,
                replied     INTEGER NOT NULL DEFAULT 0
            );
        """)

        # Seed default projects if table is empty
        existing = con.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        if existing == 0:
            seed_projects = [
                (
                    "proj-1",
                    "Project one",
                    "A full-stack web app with a clean animated UI, built with React, Node, and a custom API layer.",
                    json.dumps(["React", "Node.js", "PostgreSQL"]),
                    "💻",
                    4,
                ),
                (
                    "proj-2",
                    "Design system",
                    "A component library and design tokens used across multiple products.",
                    json.dumps(["Figma", "Storybook"]),
                    "🎨",
                    2,
                ),
                (
                    "proj-3",
                    "Performance audit",
                    "Cut load time by 60% for a client's marketing site through bundle and asset optimization.",
                    json.dumps(["Lighthouse", "Vite"]),
                    "⚡",
                    2,
                ),
            ]
            con.executemany(
                "INSERT INTO projects (id, title, description, tags, icon, span) VALUES (?,?,?,?,?,?)",
                seed_projects,
            )

        # Seed default donate links if table is empty
        existing = con.execute("SELECT COUNT(*) FROM donate").fetchone()[0]
        if existing == 0:
            seed_donate = [
                ("Ko-fi", "", "One-time support", "☕"),
                ("GitHub Sponsors", "", "Monthly support", "💵"),
                ("PayPal", "", "Direct donation", "✌"),
            ]
            con.executemany(
                "INSERT INTO donate (name, url, label, icon) VALUES (?,?,?,?)",
                seed_donate,
            )


init_db()


def row_to_project(row) -> dict:
    return {
        "id":          row["id"],
        "title":       row["title"],
        "description": row["description"],
        "tags":        json.loads(row["tags"]),
        "icon":        row["icon"],
        "span":        row["span"],
    }


def row_to_donate(row) -> dict:
    return {
        "name":  row["name"],
        "url":   row["url"],
        "label": row["label"],
        "icon":  row["icon"],
    }


def row_to_submission(row) -> dict:
    return {
        "id":        row["id"],
        "name":      row["name"],
        "email":     row["email"],
        "message":   row["message"],
        "timestamp": row["timestamp"],
        "replied":   bool(row["replied"]),
    }


# ── Auth ──────────────────────────────────────────────────────────────────────

def require_secret(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if request.headers.get("X-Secret") != API_SECRET:
            abort(401)
        return fn(*args, **kwargs)
    return wrapper


# ── CORS ──────────────────────────────────────────────────────────────────────

@app.after_request
def cors(response):
    response.headers["Access-Control-Allow-Origin"]  = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Secret"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PATCH,DELETE,OPTIONS"
    return response


@app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def options(_path):
    return "", 204


# ── Projects ──────────────────────────────────────────────────────────────────

@app.route("/projects", methods=["GET"])
def get_projects():
    with get_db() as con:
        rows = con.execute("SELECT * FROM projects ORDER BY created_at ASC").fetchall()
    return jsonify({"projects": [row_to_project(r) for r in rows]})


@app.route("/projects", methods=["POST"])
@require_secret
def add_project():
    data = request.get_json(force=True)
    required = {"title", "description", "tags"}
    if not required.issubset(data):
        return jsonify({"error": f"Missing fields: {sorted(required - data.keys())}"}), 400

    if not isinstance(data["tags"], list):
        return jsonify({"error": "tags must be a list"}), 400

    project_id = "proj-" + uuid.uuid4().hex[:6]
    span = data.get("span", 2)
    try:
        span = int(span)
    except (TypeError, ValueError):
        return jsonify({"error": "span must be an integer"}), 400

    with get_db() as con:
        con.execute(
            "INSERT INTO projects (id, title, description, tags, icon, span) VALUES (?,?,?,?,?,?)",
            (
                project_id,
                data["title"],
                data["description"],
                json.dumps(data["tags"]),
                data.get("icon", "💻"),
                span,
            ),
        )
        row = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()

    return jsonify(row_to_project(row)), 201


@app.route("/projects/<project_id>", methods=["PATCH"])
@require_secret
def edit_project(project_id):
    with get_db() as con:
        row = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404

        data = request.get_json(force=True)
        allowed = {"title", "description", "tags", "icon", "span"}
        updates = {}
        for key in allowed.intersection(data):
            if key == "span":
                try:
                    updates[key] = int(data[key])
                except (TypeError, ValueError):
                    return jsonify({"error": "span must be an integer"}), 400
            elif key == "tags":
                if not isinstance(data[key], list):
                    return jsonify({"error": "tags must be a list"}), 400
                updates[key] = json.dumps(data[key])
            else:
                updates[key] = data[key]

        if updates:
            set_clause = ", ".join(f"{k}=?" for k in updates)
            con.execute(
                f"UPDATE projects SET {set_clause} WHERE id=?",
                (*updates.values(), project_id),
            )

        row = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()

    return jsonify(row_to_project(row))


@app.route("/projects/<project_id>", methods=["DELETE"])
@require_secret
def delete_project(project_id):
    with get_db() as con:
        row = con.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404
        con.execute("DELETE FROM projects WHERE id=?", (project_id,))
    return jsonify({"deleted": project_id})


# ── Donate ────────────────────────────────────────────────────────────────────

@app.route("/donate", methods=["GET"])
def get_donate():
    with get_db() as con:
        rows = con.execute("SELECT * FROM donate").fetchall()
    return jsonify({"links": [row_to_donate(r) for r in rows]})


@app.route("/donate", methods=["POST"])
@require_secret
def set_donate():
    data = request.get_json(force=True)
    if not {"name", "url", "label"}.issubset(data):
        return jsonify({"error": "Missing fields"}), 400

    name = data["name"]
    url = data["url"]
    label = data["label"]

    with get_db() as con:
        existing = con.execute(
            "SELECT * FROM donate WHERE name=?", (name,)
        ).fetchone()

        if existing:
            icon = data.get("icon", existing["icon"])
            con.execute(
                "UPDATE donate SET url=?, label=?, icon=? WHERE name=?",
                (url, label, icon, name),
            )
            row = con.execute("SELECT * FROM donate WHERE name=?", (name,)).fetchone()
            return jsonify(row_to_donate(row))

        icon = data.get("icon", "🔗")
        con.execute(
            "INSERT INTO donate (name, url, label, icon) VALUES (?,?,?,?)",
            (name, url, label, icon),
        )
        row = con.execute("SELECT * FROM donate WHERE name=?", (name,)).fetchone()

    return jsonify(row_to_donate(row)), 201


@app.route("/donate/<name>", methods=["DELETE"])
@require_secret
def delete_donate(name):
    with get_db() as con:
        # Case-insensitive lookup, same as original behaviour
        row = con.execute(
            "SELECT name FROM donate WHERE lower(name)=lower(?)", (name,)
        ).fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404
        con.execute("DELETE FROM donate WHERE lower(name)=lower(?)", (name,))
    return jsonify({"deleted": name})


# ── Contact form proxy ────────────────────────────────────────────────────────

@app.route("/contact", methods=["POST"])
def contact():
    """
    The portfolio form POSTs here. We forward to Discord as a rich embed
    and store the submission so the bot can list pending replies.
    """
    data = request.get_json(force=True)
    name    = (data.get("name") or "").strip()
    email   = (data.get("email") or "").strip()
    message = (data.get("message") or "").strip()

    if not name or not email or not message:
        return jsonify({"error": "name, email, and message are required"}), 400

    submission_id = uuid.uuid4().hex[:8]
    timestamp = datetime.now(timezone.utc).isoformat()

    with get_db() as con:
        con.execute(
            "INSERT INTO submissions (id, name, email, message, timestamp) VALUES (?,?,?,?,?)",
            (submission_id, name, email, message, timestamp),
        )

    if WEBHOOK_URL:
        try:
            requests.post(
                WEBHOOK_URL,
                json={
                    "embeds": [{
                        "title": "📬 New portfolio message",
                        "color": 0xC861FF,
                        "fields": [
                            {"name": "Name",    "value": name,    "inline": True},
                            {"name": "Email",   "value": email,   "inline": True},
                            {"name": "Message", "value": message},
                            {"name": "ID",      "value": f"`{submission_id}`  — use `/reply` to respond", "inline": False},
                        ],
                        "timestamp": timestamp,
                    }]
                },
                timeout=5,
            )
        except Exception:
            pass  # don't fail the form if Discord is down

    return jsonify({"ok": True, "id": submission_id})


@app.route("/submissions", methods=["GET"])
@require_secret
def list_submissions():
    with get_db() as con:
        rows = con.execute(
            "SELECT * FROM submissions ORDER BY timestamp DESC"
        ).fetchall()
    return jsonify({"submissions": [row_to_submission(r) for r in rows]})


# ── Static / index ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return app.send_static_file("index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
