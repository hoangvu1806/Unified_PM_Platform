from __future__ import annotations

import argparse
from pathlib import Path

from wiki.llm_config import build_sorter, load_dotenv
from wiki.models import Actor
from wiki.paths import MVP_ROOT, data_dir
from wiki.pdf_write import write_pdf
from wiki.samples import BRD_F001_PAGES, BRD_F002_PAGES, COMPANY_CONV_PAGES, POL_WH_001_PAGES
from wiki.service import WikiService


def write_all_samples(samples_dir: Path) -> dict[str, Path]:
    samples_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "BRD-F-001-phe-duyet.pdf": BRD_F001_PAGES,
        "CONV-ENG-001-company.pdf": COMPANY_CONV_PAGES,
        "BRD-F-002-kho-vat-tu.pdf": BRD_F002_PAGES,
        "POL-WH-001-kho-spend.pdf": POL_WH_001_PAGES,
    }
    written: dict[str, Path] = {}
    for name, pages in files.items():
        path = samples_dir / name
        write_pdf(path, pages)
        written[name] = path
    return written


def run(root: Path, *, approve: bool) -> None:
    load_dotenv(root)
    svc = WikiService(root, sorter=build_sorter())
    samples = write_all_samples(data_dir(root) / "samples")
    human = Actor(actor="ba.lead", actor_type="human", project_id="PRJ-MES-01")
    jobs = [
        (
            "BRD-F-001-phe-duyet.pdf",
            "project",
            "PRJ-MES-01",
            "SRC-BRD-001",
        ),
        (
            "CONV-ENG-001-company.pdf",
            "company",
            None,
            "SRC-CONV-001",
        ),
        (
            "BRD-F-002-kho-vat-tu.pdf",
            "project",
            "PRJ-MES-01",
            "SRC-BRD-002",
        ),
        (
            "POL-WH-001-kho-spend.pdf",
            "company",
            None,
            "SRC-POL-001",
        ),
    ]
    for filename, namespace, project_id, source_id in jobs:
        actor = human if project_id else Actor(actor="ba.lead", actor_type="human")
        result = svc.ingest_source(
            actor,
            filename=filename,
            data=samples[filename].read_bytes(),
            namespace=namespace,
            project_id=project_id,
            source_id=source_id,
        )
        print("ingest:", result)
        if approve:
            who = Actor(
                actor="ba.lead",
                actor_type="human",
                project_id=project_id,
            )
            for page_id in result["proposed_page_ids"]:
                page = svc.approve_page(who, page_id)
                print("approved:", page.page_id, page.version, page.status)
    svc.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed sample PDFs into instance DB")
    parser.add_argument("--approve", action="store_true", help="approve draft pages after sort")
    parser.add_argument("--root", type=Path, default=MVP_ROOT)
    args = parser.parse_args()
    run(args.root, approve=args.approve)


if __name__ == "__main__":
    main()
