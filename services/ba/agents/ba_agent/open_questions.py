"""Dedicated Open Questions resolution, synchronization, and reply workflow."""

from __future__ import annotations

from google.adk import Context, Event
from google.adk.workflow import Workflow, node

from agents.ba_agent.constants import (
    AUTHOR_OPEN_QUESTIONS,
    TIER1_SECTIONS,
)
from agents.ba_agent.section_gate import can_proceed_to_validation, section_is_complete
from agents.sub_graph.feature_definition.nodes.oq_asm_detector.callback import (
    OQ_SYNC_VERSION,
    apply_oq_resolutions,
    ensure_oq_sync_queue,
    resolutions_from_user_message,
)
from agents.sub_graph.feature_definition.nodes.oq_asm_detector.node import (
    create_oq_asm_detector_node,
    create_oq_followthrough_node,
)

ROUTE_DETECT = "detect"
ROUTE_SYNC = "sync"


def _user_text(ctx: Context) -> str:
    content = getattr(ctx, "user_content", None)
    parts = getattr(content, "parts", None) or []
    return "\n".join(
        str(getattr(part, "text", "") or "") for part in parts
    ).strip()


def route_open_questions_state(state: dict) -> str:
    """Route retryable answers directly to sync; otherwise analyze new text."""
    queue = ensure_oq_sync_queue(state)
    has_unresolved_questions = any(
        str(item.get("status") or "open").lower() != "resolved"
        for item in (state.get("open_questions") or [])
    )
    return ROUTE_SYNC if queue and not has_unresolved_questions else ROUTE_DETECT


@node(name="open_questions_dispatch")
def open_questions_dispatch_node(ctx: Context) -> str:
    """Record explicitly keyed answers and skip detection when they are sufficient."""
    user_text = _user_text(ctx)
    explicit_resolutions = resolutions_from_user_message(user_text)
    if explicit_resolutions:
        apply_oq_resolutions(ctx.state, explicit_resolutions)
        ctx.state["_oq_user_explicit_answer_ids"] = [
            item["id"] for item in explicit_resolutions
        ]
    else:
        ctx.state["_oq_user_explicit_answer_ids"] = []

    queue = ensure_oq_sync_queue(ctx.state)
    if queue and explicit_resolutions:
        ctx.route = ROUTE_SYNC
    else:
        ctx.route = route_open_questions_state(ctx.state)
    return user_text


@node(name="open_questions_sync_sequentially", rerun_on_resume=True)
async def sync_open_questions_sequentially(ctx: Context):
    """Call the artifact updater once per OQ, applying each result before the next."""
    state = ctx.state
    turn = state.get("current_turn")
    queue = list(ensure_oq_sync_queue(state))
    previous_result = state.get("_oq_sync_result") or {}
    if previous_result.get("turn") != turn:
        state["_oq_sync_result"] = {
            "turn": turn,
            "updated_artifacts": [],
            "pending_oq_ids": [],
            "errors": [],
            "review": {},
        }
    state["_oq_sync_processed_ids"] = []
    state["_oq_sync_version"] = OQ_SYNC_VERSION

    followthrough = create_oq_followthrough_node()
    for item in queue:
        oq_id = str(item.get("id") or "").upper()
        question = next(
            (oq for oq in (state.get("open_questions") or [])
             if str(oq.get("id") or "").upper() == oq_id),
            None,
        )
        if not question or question.get("sync_status") == "verified":
            continue

        state["_oq_sync_current_id"] = oq_id
        run_id = f"oq_sync_t{turn}_{oq_id.replace('-', '_')}"
        try:
            await ctx.run_node(
                followthrough,
                node_input=f"Synchronize only {oq_id} using its supplied answer and referenced artifacts.",
                run_id=run_id,
            )
        except Exception as exc:  # noqa: BLE001
            question["sync_status"] = "failed"
            result = state.get("_oq_sync_result") or {}
            errors = list(result.get("errors") or [])
            detail = f"{oq_id}: {type(exc).__name__}: {exc}"
            if detail not in errors:
                errors.append(detail)
            result["turn"] = turn
            result["errors"] = errors
            state["_oq_sync_result"] = result
            state["open_questions"] = list(state.get("open_questions") or [])
            ensure_oq_sync_queue(state)
            state["_oq_sync_processed_ids"] = [
                *state.get("_oq_sync_processed_ids", []), oq_id
            ]
            # Keep going: one slow OQ must not block the remaining answers.
            # The failed OQ remains queued for a later retry.
        else:
            processed = list(state.get("_oq_sync_processed_ids") or [])
            if oq_id not in processed:
                processed.append(oq_id)
            state["_oq_sync_processed_ids"] = processed

    state["_oq_sync_current_id"] = None
    remaining = ensure_oq_sync_queue(state)
    result = state.get("_oq_sync_result") or {}
    result["turn"] = turn
    result["pending_oq_ids"] = [str(item.get("id") or "").upper() for item in remaining]
    state["_oq_sync_result"] = result
    if not remaining:
        state["_oq_sync_version"] = OQ_SYNC_VERSION
    yield Event(output="Open Question synchronization attempts completed.")


@node(name=AUTHOR_OPEN_QUESTIONS)
def open_questions_reply_node(ctx: Context) -> str:
    """Return a deterministic status so sync results cannot be hidden by an LLM."""
    return format_open_questions_reply(ctx.state)


def format_open_questions_reply(state: dict) -> str:
    """Build a user-facing reply from persisted OQ and sync state."""
    current_turn = state.get("current_turn")
    result = state.get("_oq_sync_result") or {}
    if result.get("turn") != current_turn:
        result = {}

    oq_by_id = {
        str(item.get("id") or "").upper(): item
        for item in (state.get("open_questions") or [])
    }
    pending_ids = list(result.get("pending_oq_ids") or [])
    pending_ids.extend(
        oq_id
        for oq_id, item in oq_by_id.items()
        if item.get("sync_status") in {"pending", "failed"} and oq_id not in pending_ids
    )
    if pending_ids:
        lines: list[str] = []
        lines.append("Mình đã ghi nhận câu trả lời, nhưng chưa cập nhật xong các phần BA liên quan:")
        for oq_id in pending_ids:
            question = oq_by_id.get(str(oq_id).upper(), {})
            refs = question.get("affected_artifacts") or []
            ids = [
                str(ref.get("artifact_id") or "")
                for ref in refs
                if isinstance(ref, dict) and ref.get("artifact_id")
            ]
            suffix = f" — phần cần cập nhật: {', '.join(ids)}" if ids else ""
            lines.append(f"- **{oq_id}**{suffix}")
        unresolved = [
            item for item in oq_by_id.values()
            if str(item.get("status") or "open").lower() != "resolved"
        ]
        if unresolved:
            lines.append("CÃ²n cÃ¢u há»i chÆ°a Ä‘Æ°á»£c báº¡n tráº£ lá»i:")
            lines.extend(
                f"- **{item.get('id', 'OQ')}**: {item.get('question', '')}"
                for item in unresolved
            )
            lines.append("Báº¡n cÃ³ thá»ƒ tráº£ lá»i cÃ¡c cÃ¢u cÃ²n thiáº¿u theo mÃ£ OQ; cÃ¡c cÃ¢u Ä‘Ã£ tráº£ lá»i sáº½ Ä‘Æ°á»£c giá»¯ láº¡i.")
        if result.get("errors"):
            lines.append("Chi tiết: " + "; ".join(result["errors"]))
        lines.append(
            "Một số artifact chưa xác nhận đồng bộ. Bạn vẫn có thể chạy Validate; "
            "kết quả sẽ rà trên artifact hiện tại và nêu rõ cảnh báo này. "
            "Hãy đối chiếu các cảnh báo trước khi bàn giao Designer. Câu trả lời đã ghi nhận sẽ được giữ lại."
        )
        return "\n".join(lines)

    if result:
        lines = []
        updated = result.get("updated_artifacts") or []
        if updated:
            lines.append("Đã đồng bộ câu trả lời vào: " + ", ".join(f"`{item}`" for item in updated) + ".")
        else:
            lines.append("Đã rà soát artifact phụ thuộc; không cần thay đổi artifact nào theo các câu trả lời này.")
        review = result.get("review") or {}
        failed = review.get("failed_checks") or []
        if failed:
            lines.append("Rà soát package còn mục cần xử lý trước Validate:")
            lines.extend(
                f"- **{item.get('check_id', '')} {item.get('name', '')}:** {item.get('detail', '')}"
                for item in failed
            )
            return "\n".join(lines)
        unresolved = [
            item for item in (state.get("open_questions") or [])
            if str(item.get("status") or "open").lower() != "resolved"
        ]
        if unresolved:
            lines.append("CÃ²n cÃ¢u há»i cáº§n báº¡n chá»‘t:")
            lines.extend(
                f"- **{item.get('id', 'OQ')}** ({item.get('severity', 'warning')}): {item.get('question', '')}"
                for item in unresolved
            )
            lines.append("Tráº£ lá»i theo mÃ£ OQ; cÃ¡c cÃ¢u Ä‘Ã£ Ä‘á»“ng bá»™ khÃ´ng cáº§n tráº£ lá»i láº¡i.")
            return "\n".join(lines)
        if can_proceed_to_validation(state):
            lines.append("Đã rà soát package, hiện không còn blocker đã phát hiện ở bước này. Bạn có thể chạy Validate chính thức.")
        else:
            incomplete = [
                section for section in TIER1_SECTIONS
                if not section_is_complete(state, section)
            ]
            needs_review = [
                section for section, status in (state.get("sections_status") or {}).items()
                if status == "needs_review"
            ]
            lines.append("Đồng bộ OQ đã xong, nhưng package chưa đủ điều kiện Validate.")
            if incomplete:
                lines.append("Cần hoàn tất: " + ", ".join(f"`{item}`" for item in incomplete) + ".")
            if needs_review:
                lines.append("Cần rà soát lại: " + ", ".join(f"`{item}`" for item in needs_review) + ".")
        return "\n".join(lines)

    unresolved = [
        item for item in (state.get("open_questions") or [])
        if str(item.get("status") or "open").lower() != "resolved"
    ]
    if unresolved:
        lines = []
        lines.append("Các Open Question sau vẫn cần câu trả lời rõ ràng:")
        lines.extend(
            f"- **{item.get('id', 'OQ')}** ({item.get('severity', 'warning')}): {item.get('question', '')}"
            for item in unresolved
        )
        lines.append("Trả lời theo mẫu `OQ-001: <quyết định>` để hệ thống ghi nhận đúng câu hỏi.")
    else:
        lines.append(
            "Mình đã nhận tin nhắn nhưng chưa có kết quả đồng bộ mới trong lượt này. "
            "Mình sẽ kiểm tra lại các câu trả lời và artifact liên quan trước khi báo trạng thái hoàn tất."
        )
    return "\n".join(lines)


def create_open_questions_subgraph() -> Workflow:
    """Run detection only when needed, then sync and report actual status."""
    detector = create_oq_asm_detector_node()
    return Workflow(
        name="open_questions_resolution_workflow",
        edges=[
            ("START", open_questions_dispatch_node),
            (
                open_questions_dispatch_node,
                {
                    ROUTE_DETECT: detector,
                    ROUTE_SYNC: sync_open_questions_sequentially,
                },
            ),
            (detector, sync_open_questions_sequentially),
            (sync_open_questions_sequentially, open_questions_reply_node),
        ],
    )


open_questions_subgraph = create_open_questions_subgraph()
