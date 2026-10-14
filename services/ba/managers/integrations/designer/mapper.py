"""Map the BA Common Envelope to the stable Designer handoff contract."""

from __future__ import annotations

from typing import Any


def _assets(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for asset in payload.get("reference_assets") or []:
        if not isinstance(asset, dict) or not asset.get("id") or not asset.get("filename"):
            continue
        uri = str(asset.get("uri") or "")
        data_mime = ""
        if uri.startswith("data:") and ";" in uri[5:]:
            data_mime = uri[5:].split(";", 1)[0]
        result.append(
            {
                "id": str(asset["id"]),
                "name": str(asset.get("filename") or asset["id"]),
                "mime_type": str(asset.get("mime_type") or data_mime or "image/png"),
                "usage": "exact",
                "visual_role": str(asset.get("visual_role") or "image"),
                "recommended_fit": "contain",
                "recommended_placement": "content area",
            }
        )
    return result[:4]


def _asset_data_urls(payload: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for asset in payload.get("reference_assets") or []:
        if not isinstance(asset, dict) or not asset.get("id"):
            continue
        uri = str(asset.get("uri") or "")
        if uri.startswith("data:image/"):
            result[str(asset["id"])] = uri
    return result


def build_designer_handoff(envelope: dict[str, Any]) -> dict[str, Any]:
    payload = envelope.get("payload") or {}
    title = str(payload.get("feature_title") or "BA feature")
    # Common Envelope keeps correlation_id/feature_id at the top level.
    correlation_id = str(envelope.get("correlation_id") or "")
    feature_id = str(envelope.get("feature_id") or correlation_id)
    # Version the integration identity so packages created by the old
    # prompt-only adapter are not incorrectly reused after this attachment
    # handoff upgrade.
    handoff_correlation_id = f"{correlation_id or feature_id}:designer-v2"
    return {
        "source_agent": "ba-agent",
        "correlation_id": handoff_correlation_id,
        "feature_id": feature_id,
        "title": title,
        "prompt": (
            "Analyze the attached approved BA package as the source of truth. "
            "Determine the screen scope and ask for approval before designing."
        ),
        "screen_name": title[:120],
        "platform": "responsive",
        "assets": _assets(payload),
        "asset_data_urls": _asset_data_urls(payload),
        "ba_package": envelope,
    }
