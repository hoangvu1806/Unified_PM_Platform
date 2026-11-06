"""Retrieval over the vendored design knowledge (see ``knowledge/README.md``).

Two sources, used as data only:
- ui-ux-pro-max (MIT): product profiles, palettes, font pairings, UX/app guidelines, charts,
  landing patterns, HTML/Tailwind rules and the pre-delivery checklist — searched with BM25 so
  any domain or platform gets the rows that fit it;
- Anthropic's frontend-design skill (Apache-2.0): aesthetic principles for the builder.
"""

from __future__ import annotations

import csv
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2] / "knowledge"
UUPM = ROOT / "ui-ux-pro-max"
_WORD = re.compile(r"[a-z0-9]+")
DONT = "Don't"
_STOP = {"and", "or", "the", "a", "an", "of", "for", "to", "with", "in", "on", "app", "ui"}


def _tokens(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if t not in _STOP and len(t) > 1]


class Table:
    """CSV rows with a BM25 index over the given columns."""

    def __init__(self, path: Path, fields: list[str], keep=lambda row: True) -> None:
        with path.open(encoding="utf-8") as f:
            self.rows = [r for r in csv.DictReader(f) if keep(r)]
        self.docs = [_tokens(" ".join(r.get(c, "") for c in fields)) for r in self.rows]
        self.avg = sum(map(len, self.docs)) / max(len(self.docs), 1)
        df = Counter(t for d in self.docs for t in set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tf = [Counter(d) for d in self.docs]

    def search(self, query: str, k: int = 3, where=lambda row: True) -> list[dict[str, str]]:
        terms = _tokens(query)
        scored = []
        for row, tf, doc in zip(self.rows, self.tf, self.docs):
            if not where(row):
                continue
            score = sum(
                self.idf.get(t, 0) * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(doc) / self.avg))
                for t in terms if t in tf
            )
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda x: -x[0])
        return [row for _, row in scored[:k]]


@lru_cache
def _tables() -> dict[str, Table]:
    d = UUPM / "datasets"  # upstream "data/" (renamed: data/ is ignored as runtime output)
    return {
        "products": Table(d / "products.csv", ["Product Type", "Keywords", "Product Type", "Key Considerations"]),
        "reasoning": Table(d / "ui-reasoning.csv", ["UI_Category"]),
        "colors": Table(d / "colors.csv", ["Product Type"]),
        "styles": Table(d / "styles.csv", ["Style Category", "Aliases", "Keywords", "Best For"],
                        keep=lambda r: r.get("Status") in {"active", "supplemental"}),
        "typography": Table(d / "typography.csv", ["Mood/Style Keywords", "Best For", "Category", "Font Pairing Name"]),
        "ux": Table(d / "ux-guidelines.csv", ["Category", "Issue", "Description", "Do"]),
        "app": Table(d / "app-interface.csv", ["Category", "Issue", "Keywords", "Description"]),
        "charts": Table(d / "charts.csv", ["Data Type", "Keywords", "Best Chart Type"]),
        "landing": Table(d / "landing.csv", ["Pattern Name", "Keywords", "Aliases"]),
        "tailwind": Table(d / "stacks" / "html-tailwind.csv", ["Category", "Guideline", "Description", "Do"],
                          keep=lambda r: r.get("Status", "active") == "active"),
    }


def _same(table: str, column: str, value: str) -> dict[str, str] | None:
    return next((r for r in _tables()[table].rows if r.get(column, "").strip().lower() == value.strip().lower()), None)


def product_profile(query: str) -> dict[str, Any] | None:
    """Best matching product type with its reasoning, palette, style and font pairings."""
    t = _tables()
    hit = t["products"].search(query, 1)
    if not hit:
        return None
    product = hit[0]
    kind = product["Product Type"]
    reasoning = _same("reasoning", "UI_Category", kind) or {}
    style_name = (product.get("Primary Style Recommendation") or "").split("+")[0].strip()
    style = t["styles"].search(style_name, 1)
    fonts = t["typography"].search(f"{reasoning.get('Typography_Mood', '')} {kind} {query}", 2)
    return {"product": product, "reasoning": reasoning, "colors": _same("colors", "Product Type", kind) or {},
            "style": style[0] if style else {}, "fonts": fonts}


def style_preview_candidates(query: str, k: int = 3) -> list[dict[str, Any]]:
    """Return a few distinct, domain-relevant style recipes for visual previews."""
    table = _tables()["styles"]
    profile = product_profile(query)
    names: list[str] = []
    if profile:
        product = profile["product"]
        for field in ("Primary Style Recommendation", "Secondary Styles"):
            names.extend(part.strip() for part in re.split(r"[+,;/]", product.get(field, "")) if part.strip())
    names.extend(row["Style Category"] for row in table.search(query, 12))

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in names:
        row = table.search(name, 1)
        if not row:
            continue
        item = row[0]
        key = item.get("Style ID") or item.get("Style Category", "").lower().replace(" ", "-")
        if not key or key in seen:
            continue
        seen.add(key)
        tokens = {
            name.lower().replace("_", "-"): color.lower()
            for name, color in re.findall(
                r"--([a-zA-Z0-9_-]+)\s*:\s*(#[0-9a-fA-F]{6})", item.get("Design System Variables", "")
            )
        }
        source_colors = [color.lower() for color in re.findall(
            r"#[0-9a-fA-F]{6}", item.get("Primary Colors", "") + " " + item.get("Secondary Colors", "")
        )]
        pick = lambda *names, fallback: next((tokens[name] for name in names if name in tokens), fallback)
        primary = pick("primary", "accent-primary", "accent-color", "accent", fallback=source_colors[0] if source_colors else "#2563eb")
        background = pick("bg", "background", fallback="#ffffff")
        foreground = pick("fg", "foreground", fallback="#111827")
        surface = pick("card", "surface", "bg-alt", fallback="#ffffff")
        accent = pick("accent-secondary", "accent", fallback=source_colors[1] if len(source_colors) > 1 else primary)
        palette = {
            "primary": primary, "primary_foreground": pick("primary-foreground", "on-primary", fallback="#ffffff"),
            "background": background, "foreground": foreground, "surface": surface,
            "muted": pick("muted", "bg-muted", fallback="#f1f5f9"),
            "muted_foreground": pick("muted-fg", "muted-foreground", fallback="#64748b"),
            "border": pick("border", fallback="#e2e8f0"), "accent": accent,
            "success": pick("success", fallback="#16a34a"),
            "warning": pick("warning", fallback="#d97706"),
            "destructive": pick("destructive", "danger", fallback="#dc2626"),
        }
        results.append({
            "key": key,
            "name": item.get("Style Category", name),
            "tagline": (item.get("Era/Origin", "") + " · " + item.get("Best For", ""))[:230],
            "direction": (item.get("AI Prompt Keywords", "") or item.get("Keywords", ""))[:1_900],
            "palette": palette,
            "heading_font": "",
            "body_font": "",
            "radius": "lg",
            "density": "comfortable",
            "composition": item.get("CSS/Technical Keywords", "")[:500],
            "surface_language": item.get("Effects & Animation", "")[:500],
            "shape_language": item.get("Keywords", "")[:500],
            "hero_placement": "Use a product-relevant focal visual in a dedicated hero/background area when the screen task benefits from it.",
        })
        if len(results) >= k:
            break
    return results


def profile_text(profile: dict[str, Any] | None) -> str:
    """Compact brief of a product profile for the spec / art-direction prompt."""
    if not profile:
        return "No matching product profile: derive the direction from the product itself."
    p, r, c, s = profile["product"], profile["reasoning"], profile["colors"], profile["style"]
    palette = ", ".join(f"{k} {c[k]}" for k in ("Primary", "On Primary", "Accent", "Background", "Foreground",
                                                   "Card", "Muted", "Muted Foreground", "Border", "Destructive") if c.get(k))
    fonts = "; ".join(f"{f['Heading Font']} / {f['Body Font']} ({f['Mood/Style Keywords']})" for f in profile["fonts"])
    lines = [
        f"Closest product type: {p['Product Type']}. {p.get('Key Considerations', '')}",
        f"Style: {p.get('Primary Style Recommendation', '')} (alternatives: {p.get('Secondary Styles', '')}); "
        f"dashboard: {p.get('Dashboard Style (if applicable)', '')}.",
        f"Color mood: {r.get('Color_Mood') or p.get('Color Palette Focus', '')}. Reference palette: {palette}.",
        f"Typography mood: {r.get('Typography_Mood', '')}. Candidate pairings (heading / body): {fonts}.",
        f"Effects: {r.get('Key_Effects', '')}. Avoid: {r.get('Anti_Patterns', '')}.",
    ]
    if s:
        lines.append(f"Style '{s['Style Category']}': {s.get('Keywords', '')[:220]}. Not for: {s.get('Do Not Use For', '')[:160]}.")
    return "\n".join(f"- {line}" for line in lines)


def ux_rules(query: str, platform: str, k: int = 8) -> list[str]:
    """UX guidelines (and app-interface rules on mobile) that fit this screen."""
    t = _tables()
    mobile = platform == "mobile"
    allowed = {"All", "Mobile"} if mobile else {"All", "Web"}
    rows = t["ux"].search(query, k, where=lambda r: r.get("Platform") in allowed)
    out = [_rule(r) for r in rows]
    if mobile:
        out += [_rule(r) for r in t["app"].search(query, 3)]
    return out


def _rule(row: dict[str, str]) -> str:
    return f"{row['Issue']}: {row['Do']} — avoid: {row.get(DONT, '')}"


def chart_rules(query: str, k: int = 2) -> list[str]:
    return [f"{r['Data Type']}: {r['Best Chart Type']} (when: {r['When to Use']}; not when: {r['When NOT to Use']})"
            for r in _tables()["charts"].search(query, k)]


def landing_pattern(query: str) -> str:
    hit = _tables()["landing"].search(query, 1)
    return f"{hit[0]['Pattern Name']}: {hit[0]['Section Order']}. CTA: {hit[0]['Primary CTA Placement']}." if hit else ""


def tailwind_rules(query: str, k: int = 4) -> list[str]:
    return [f"{r['Guideline']}: {r['Do']}" for r in _tables()["tailwind"].search(query, k)]


@lru_cache
def frontend_design_skill() -> str:
    text = (ROOT / "frontend-design" / "SKILL.md").read_text(encoding="utf-8")
    return text.split("---", 2)[2].strip() if text.startswith("---") else text


@lru_cache
def style_preview_skill() -> str:
    """Project-aware workflow for designing, rendering, and critiquing style previews."""
    return (ROOT / "style-preview" / "SKILL.md").read_text(encoding="utf-8").strip()


@lru_cache
def ui_ux_design_rules() -> str:
    """Required product-independent UI/UX rules for specifying, building, and reviewing screens."""
    files = (
        "material-ui-ux-knowledge-reference.md",
        "multi-screen-design-rules.md",
        "screen-sequence-identity-and-content.md",
    )
    return "\n\n---\n\n".join(
        (ROOT / name).read_text(encoding="utf-8").strip() for name in files
    )


@lru_cache
def review_checklist() -> str:
    """Visual quality, layout and accessibility parts of ui-ux-pro-max's pre-delivery checklist."""
    text = (UUPM / "references" / "pro-rules.md").read_text(encoding="utf-8")
    keep, out = False, []
    for line in text.splitlines():
        if line.startswith("### "):
            keep = line[4:].strip() in {"Visual Quality", "Layout", "Accessibility"}
        if keep and line.startswith("- [ ]"):
            out.append("- " + line[6:])
    return "\n".join(out)
