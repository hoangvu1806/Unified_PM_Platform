"""Demo accounts for AUTH_MODE=mock (idempotent).

``MOCK_SEED=minimal`` (default): only the two PM accounts, no projects — users
create their own. ``MOCK_SEED=full``: every role plus two sample projects, used
by the test suites and ``scripts/e2e_access.py``.
"""

from __future__ import annotations

import os

from .db import connection
from .passwords import hash_password

DEMO_PASSWORD = "demo123"

USERS = [
    # id, username, display name, platform roles
    ("u-pm-hoa", "pm.hoa", "Hòa (PM)", ["BA", "DESIGNER"]),
    ("u-ba-an", "ba.an", "An (BA)", ["BA"]),
    ("u-ba-chi", "ba.chi", "Chi (BA)", ["BA"]),
    ("u-designer-binh", "designer.binh", "Bình (Designer)", ["DESIGNER"]),
    ("u-lead-dung", "lead.dung", "Dũng (PM)", ["BA", "DESIGNER"]),
]
PM_USERS = {"u-pm-hoa", "u-lead-dung"}

PROJECTS = [
    ("PRJ-AURORA", "Aurora", "Multi-plant deviation, CAPA and recall orchestration", "u-lead-dung"),
    ("PRJ-DEMO", "Demo Portal", "Sandbox project for trying the platform", "u-lead-dung"),
]

MEMBERS = [
    ("PRJ-AURORA", "u-pm-hoa", "PM"),
    ("PRJ-DEMO", "u-pm-hoa", "PM"),
    ("PRJ-AURORA", "u-ba-an", "BA"),
    ("PRJ-AURORA", "u-designer-binh", "DESIGNER"),
    ("PRJ-AURORA", "u-lead-dung", "ADMIN"),
    ("PRJ-AURORA", "u-lead-dung", "BA"),
    ("PRJ-AURORA", "u-lead-dung", "DESIGNER"),
    ("PRJ-DEMO", "u-ba-an", "BA"),
    ("PRJ-DEMO", "u-ba-chi", "BA"),
    ("PRJ-DEMO", "u-designer-binh", "DESIGNER"),
    ("PRJ-DEMO", "u-lead-dung", "ADMIN"),
    ("PRJ-DEMO", "u-lead-dung", "BA"),
    ("PRJ-DEMO", "u-lead-dung", "DESIGNER"),
]


def seed_mode() -> str:
    return "full" if os.environ.get("MOCK_SEED", "minimal").strip().lower() == "full" else "minimal"


def seed_users() -> list[tuple[str, str, str, list[str]]]:
    return USERS if seed_mode() == "full" else [u for u in USERS if u[0] in PM_USERS]


def seed_demo() -> None:
    full = seed_mode() == "full"
    with connection() as conn:
        for uid, username, name, roles in seed_users():
            conn.execute(
                "INSERT INTO users (id, username, display_name, password_hash, platform_roles) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (uid, username, name, hash_password(DEMO_PASSWORD), roles),
            )
        if not full:
            return
        for pid, name, description, owner in PROJECTS:
            conn.execute(
                "INSERT INTO projects (id, name, description, created_by) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (id) DO NOTHING",
                (pid, name, description, owner),
            )
        for pid, uid, role in MEMBERS:
            conn.execute(
                "INSERT INTO project_members (project_id, user_id, project_role) VALUES (%s, %s, %s) "
                "ON CONFLICT DO NOTHING",
                (pid, uid, role),
            )
