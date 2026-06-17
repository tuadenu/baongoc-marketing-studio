from __future__ import annotations

import sqlite3
from datetime import datetime

from .utils import root_path


DB_PATH = root_path("data", "app.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _ensure_columns(conn: sqlite3.Connection, table_name: str, columns: dict[str, str]) -> None:
    existing = _table_columns(conn, table_name)
    for column_name, ddl in columns.items():
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_name TEXT NOT NULL,
                platform TEXT NOT NULL,
                aspect_ratio TEXT NOT NULL,
                style_preset TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER,
                type TEXT,
                prompt TEXT,
                negative_prompt TEXT,
                model TEXT,
                aspect_ratio TEXT,
                status TEXT,
                output_path TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_type TEXT,
                campaign_id INTEGER,
                media_type TEXT,
                model TEXT,
                prompt TEXT,
                status TEXT,
                output_path TEXT,
                detail TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usage_costs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER,
                project_id TEXT,
                model TEXT,
                media_type TEXT,
                estimated_cost_usd REAL,
                estimated_cost_vnd REAL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS billing_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT,
                official_starting_credit_vnd REAL,
                official_used_vnd REAL,
                official_remaining_vnd REAL,
                app_estimated_used_vnd REAL,
                difference_vnd REAL,
                calibration_factor REAL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ui_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                state_key TEXT NOT NULL UNIQUE,
                state_value TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        _ensure_columns(
            conn,
            "requests",
            {
                "request_type": "TEXT",
                "campaign_id": "INTEGER",
                "media_type": "TEXT",
                "model": "TEXT",
                "prompt": "TEXT",
                "status": "TEXT",
                "output_path": "TEXT",
                "detail": "TEXT",
                "error_message": "TEXT",
                "created_at": "TEXT NOT NULL",
            },
        )
        _ensure_columns(
            conn,
            "usage_costs",
            {
                "request_id": "INTEGER",
                "project_id": "TEXT",
                "model": "TEXT",
                "media_type": "TEXT",
                "estimated_cost_usd": "REAL",
                "estimated_cost_vnd": "REAL",
                "created_at": "TEXT NOT NULL",
            },
        )
        _ensure_columns(
            conn,
            "billing_snapshots",
            {
                "project_id": "TEXT",
                "official_starting_credit_vnd": "REAL",
                "official_used_vnd": "REAL",
                "official_remaining_vnd": "REAL",
                "app_estimated_used_vnd": "REAL",
                "difference_vnd": "REAL",
                "calibration_factor": "REAL",
                "created_at": "TEXT NOT NULL",
            },
        )
        _ensure_columns(
            conn,
            "characters",
            {
                "name": "TEXT NOT NULL",
                "slug": "TEXT NOT NULL UNIQUE",
                "role": "TEXT",
                "description": "TEXT",
                "base_prompt": "TEXT",
                "reference_image_path": "TEXT",
                "created_at": "TEXT NOT NULL",
            },
        )
        _ensure_columns(
            conn,
            "ui_state",
            {
                "state_key": "TEXT NOT NULL UNIQUE",
                "state_value": "TEXT",
                "created_at": "TEXT NOT NULL",
            },
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                role TEXT,
                description TEXT,
                base_prompt TEXT,
                reference_image_path TEXT,
                created_at TEXT NOT NULL
            )
            """
        )


def create_campaign(data: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO campaigns (campaign_name, platform, aspect_ratio, style_preset, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                data["campaign_name"],
                data["platform"],
                data["aspect_ratio"],
                data["style_preset"],
                datetime.utcnow().isoformat(),
            ),
        )
        return cur.lastrowid


def list_campaigns():
    with get_conn() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM campaigns ORDER BY id DESC")]


def save_prompt(data: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO prompts (campaign_id, type, prompt, negative_prompt, model, aspect_ratio, status, output_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("campaign_id"),
                data.get("type"),
                data.get("prompt"),
                data.get("negative_prompt"),
                data.get("model"),
                data.get("aspect_ratio"),
                data.get("status", "queued"),
                data.get("output_path"),
                datetime.utcnow().isoformat(),
            ),
        )
        return cur.lastrowid


def list_prompts():
    with get_conn() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM prompts ORDER BY id DESC")]


def update_prompt_status(prompt_id: int, status: str, output_path: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE prompts SET status = ?, output_path = COALESCE(?, output_path) WHERE id = ?",
            (status, output_path, prompt_id),
        )


def log_request(
    request_type: str,
    campaign_id: int | None,
    detail: str,
    model: str | None = None,
    prompt: str | None = None,
    status: str | None = None,
    output_path: str | None = None,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO requests (request_type, campaign_id, media_type, model, prompt, status, output_path, detail, error_message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_type,
                campaign_id,
                request_type,
                model,
                prompt,
                status,
                output_path,
                detail,
                None,
                datetime.utcnow().isoformat(),
            ),
        )
        return cur.lastrowid


def update_request_status(request_id: int, status: str, output_path: str | None = None, detail: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE requests
            SET status = ?, output_path = COALESCE(?, output_path), detail = COALESCE(?, detail), error_message = COALESCE(?, error_message)
            WHERE id = ?
            """,
            (status, output_path, detail, detail if status == "failed" else None, request_id),
        )


def list_requests():
    with get_conn() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM requests ORDER BY id DESC")]


def list_recent_requests(limit: int = 20):
    with get_conn() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM requests ORDER BY id DESC LIMIT ?",
            (limit,),
        )]


def log_usage_cost(
    request_id: int,
    project_id: str,
    model: str,
    media_type: str,
    estimated_cost_usd: float,
    estimated_cost_vnd: float,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO usage_costs (request_id, project_id, model, media_type, estimated_cost_usd, estimated_cost_vnd, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                project_id,
                model,
                media_type,
                estimated_cost_usd,
                estimated_cost_vnd,
                datetime.utcnow().isoformat(),
            ),
        )


def list_usage_costs():
    with get_conn() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM usage_costs ORDER BY id DESC")]


def get_total_estimated_usage_vnd() -> float:
    with get_conn() as conn:
        row = conn.execute("SELECT COALESCE(SUM(estimated_cost_vnd), 0) AS total FROM usage_costs").fetchone()
        return float(row["total"] or 0)


def get_usage_costs_by_model():
    with get_conn() as conn:
        try:
            return [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT model, media_type,
                           COALESCE(SUM(estimated_cost_usd), 0) AS total_usd,
                           COALESCE(SUM(estimated_cost_vnd), 0) AS total_vnd,
                           COUNT(*) AS requests
                    FROM usage_costs
                    GROUP BY model, media_type
                    ORDER BY total_vnd DESC
                    """
                )
            ]
        except sqlite3.OperationalError:
            return []


def save_billing_snapshot(data: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO billing_snapshots (
                project_id,
                official_starting_credit_vnd,
                official_used_vnd,
                official_remaining_vnd,
                app_estimated_used_vnd,
                difference_vnd,
                calibration_factor,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("project_id"),
                data.get("official_starting_credit_vnd"),
                data.get("official_used_vnd"),
                data.get("official_remaining_vnd"),
                data.get("app_estimated_used_vnd"),
                data.get("difference_vnd"),
                data.get("calibration_factor"),
                datetime.utcnow().isoformat(),
            ),
        )
        return cur.lastrowid


def list_billing_snapshots(limit: int = 20):
    with get_conn() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM billing_snapshots ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        ]


def save_ui_state(state_key: str, state_value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO ui_state (state_key, state_value, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(state_key) DO UPDATE SET
                state_value = excluded.state_value,
                created_at = excluded.created_at
            """,
            (state_key, state_value, datetime.utcnow().isoformat()),
        )


def get_ui_state(state_key: str, default: str | None = None) -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT state_value FROM ui_state WHERE state_key = ?", (state_key,)).fetchone()
        return row["state_value"] if row and row["state_value"] is not None else default


def create_character(data: dict) -> int:
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM characters WHERE slug = ?", (data["slug"],)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE characters
                SET name = ?, role = ?, description = ?, base_prompt = ?, reference_image_path = ?, created_at = ?
                WHERE slug = ?
                """,
                (
                    data["name"],
                    data.get("role"),
                    data.get("description"),
                    data.get("base_prompt"),
                    data.get("reference_image_path"),
                    datetime.utcnow().isoformat(),
                    data["slug"],
                ),
            )
            return int(existing["id"])
        cur = conn.execute(
            """
            INSERT INTO characters (name, slug, role, description, base_prompt, reference_image_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["name"],
                data["slug"],
                data.get("role"),
                data.get("description"),
                data.get("base_prompt"),
                data.get("reference_image_path"),
                datetime.utcnow().isoformat(),
            ),
        )
        return cur.lastrowid


def list_characters():
    with get_conn() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM characters ORDER BY id DESC")]


def get_character_by_slug(slug: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM characters WHERE slug = ?", (slug,)).fetchone()
        return dict(row) if row else None
