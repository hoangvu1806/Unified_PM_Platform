"""Merge helpers for Business Rules artifacts."""

from __future__ import annotations

from agents.sub_graph.business_rules.schemas import BusinessRuleItem, BusinessRulesData


def merge_business_rules(
    current: list[dict], delta: BusinessRulesData
) -> list[dict]:
    rules = [dict(r) for r in current]
    if not delta.business_rules:
        return rules
    by_id = {str(r.get("id", "")): r for r in rules if r.get("id")}
    for item in delta.business_rules:
        rule = {
            "id": item.id or _next_id(rules),
            "statement": item.statement.strip(),
            "source": (item.source or "").strip() or "PO",
        }
        if rule["id"] in by_id:
            by_id[rule["id"]].update(rule)
        else:
            rules.append(rule)
            by_id[rule["id"]] = rule
    return rules


def _next_id(rules: list[dict]) -> str:
    nums = []
    for r in rules:
        rid = str(r.get("id", ""))
        if rid.startswith("BR-"):
            try:
                nums.append(int(rid.split("-", 1)[1]))
            except ValueError:
                pass
    n = max(nums, default=0) + 1
    return f"BR-{n:02d}"
