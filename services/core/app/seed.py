"""Demo accounts and projects for AUTH_MODE=mock (idempotent)."""

from __future__ import annotations

from .db import connection
from .passwords import hash_password

DEMO_PASSWORD = "demo123"

USERS = [
    # id, username, display name, platform roles
    ("u-pm-hoa", "pm.hoa", "Hòa (PM)", ["BA", "DESIGNER"]),
    ("u-ba-an", "ba.an", "An (BA)", ["BA"]),
    ("u-ba-chi", "ba.chi", "Chi (BA)", ["BA"]),
    ("u-designer-binh", "designer.binh", "Bình (Designer)", ["DESIGNER"]),
    ("u-lead-dung", "lead.dung", "Dũng (Lead)", ["BA", "DESIGNER"]),
]

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


def seed_demo() -> None:
    with connection() as conn:
        for uid, username, name, roles in USERS:
            conn.execute(
                "INSERT INTO users (id, username, display_name, password_hash, platform_roles) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (uid, username, name, hash_password(DEMO_PASSWORD), roles),
            )
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
