"""Scripted BA ↔ Wiki demo: fixed page IDs and bootstrap/reset against WikiService."""

from __future__ import annotations

from typing import Any

from wiki.models import Actor, ProposePageIn
from wiki.service import WikiService

SIM_PROJECT = "PRJ-MES-01"
SIM_NAMESPACE = "project"
SIM_FEATURE = "F-KHO-SPEND"

BOOTSTRAP_IDS = [
    "SIM-GLOSS-PO",
    "SIM-ORG-WHCLERK",
    "SIM-CONSTRAINT-SKU",
    "SIM-BR-RULE10",
]

PROPOSE_IDS = [
    "SIM-ORG-PO-SPEND",
    "SIM-CONSTRAINT-F-KHO",
    "SIM-PROGRESS-F-KHO",
]

ALL_SIM_IDS = BOOTSTRAP_IDS + PROPOSE_IDS

HUMAN = Actor(actor="ba.lead", actor_type="human", project_id=SIM_PROJECT)

BOOTSTRAP_PAGES: list[ProposePageIn] = [
    ProposePageIn(
        page_id="SIM-GLOSS-PO",
        namespace=SIM_NAMESPACE,
        project_id=SIM_PROJECT,
        bucket_id="glossary",
        title="Product Owner",
        abbrev="PO",
        expansion="Product Owner",
        body="---\nba_section: glossary\nba_id: PO\nfeature_id: SSOT\n---\nPO phe duyet Business Analysis Package va don chi tieu vuot nguong.",
        owner="ba.lead",
    ),
    ProposePageIn(
        page_id="SIM-ORG-WHCLERK",
        namespace=SIM_NAMESPACE,
        project_id=SIM_PROJECT,
        bucket_id="org",
        title="Warehouse clerk",
        abbrev="wh.clerk",
        body="---\nba_section: feature_definition\nba_id: ACT-WH-CLERK\n---\nwh.clerk: nhan vien kho de xuat don mua vat tu. Khong tu phe duyet.",
        owner="ba.lead",
    ),
    ProposePageIn(
        page_id="SIM-CONSTRAINT-SKU",
        namespace=SIM_NAMESPACE,
        project_id=SIM_PROJECT,
        bucket_id="constraint",
        title="No silent SKU substitution",
        body="---\nba_section: feature_definition\nba_id: SCOPE-OUT-SKU\n---\nKhong thay SKU am tham. Thay the vat tu phai ghi ro tren don.",
        owner="ba.lead",
    ),
    ProposePageIn(
        page_id="SIM-BR-RULE10",
        namespace=SIM_NAMESPACE,
        project_id=SIM_PROJECT,
        bucket_id="business_rule",
        title="BR-10 Nguong PO",
        abbrev="BR-10",
        body="---\nba_section: business_rules\nba_id: BR-10\nsource: Policy\n---\nKhi don > 50 trieu VND thi bat buoc PO phe duyet. Khong phe duyet tap the.",
        owner="ba.lead",
    ),
]


def list_sim_pages(svc: WikiService) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for page_id in ALL_SIM_IDS:
        row = svc.conn.execute(
            "SELECT * FROM wiki_page WHERE page_id = ?", (page_id,)
        ).fetchone()
        if row:
            out.append(
                {
                    "page_id": row["page_id"],
                    "status": row["status"],
                    "bucket_id": row["bucket_id"],
                    "title": row["title"],
                    "version": row["version"],
                }
            )
    return out


def sim_state(svc: WikiService) -> dict[str, Any]:
    approved = svc.list_pages(status="approved")
    return {
        "approved_count": len(approved),
        "sim_pages": list_sim_pages(svc),
        "project_id": SIM_PROJECT,
        "feature_id": SIM_FEATURE,
    }


def bootstrap_ssot(svc: WikiService) -> dict[str, Any]:
    """Seed canonical SIM pages only when the wiki has zero approved pages."""
    approved = svc.list_pages(status="approved")
    if approved:
        return {
            "seeded": False,
            "reason": "approved_already_present",
            "approved_count": len(approved),
            "sim_pages": list_sim_pages(svc),
        }
    created: list[str] = []
    for payload in BOOTSTRAP_PAGES:
        page = svc.propose_page(HUMAN, payload)
        svc.approve_page(HUMAN, page.page_id)
        created.append(page.page_id)
    return {
        "seeded": True,
        "reason": "empty_ssot",
        "approved_count": len(svc.list_pages(status="approved")),
        "created": created,
        "sim_pages": list_sim_pages(svc),
    }


def reset_sim_pages(svc: WikiService) -> dict[str, Any]:
    n = svc.delete_pages(ALL_SIM_IDS)
    return {"removed": n, "page_ids": ALL_SIM_IDS, "sim_pages": list_sim_pages(svc)}
