"""Before-model callback helpers for context injection.

Provides functions to inject artifact context from Database into the LLM request contents
before the latest user message.
"""

import json
from pathlib import Path

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest
from google.genai import types

from callbacks.utils import extract_session_id
from managers.database.package_repository import BaPackageRepository
from utils import format_string


def insert_context(llm_request: LlmRequest, context_text: str) -> None:
    """Insert a context user message into the LLM request contents right before the latest user message.

    Args:
        llm_request: The outgoing LLM request payload.
        context_text: The text block to inject as context.
    """
    context_content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=context_text)],
    )

    # Find position of latest user message
    insert_idx = len(llm_request.contents)
    for i in range(len(llm_request.contents) - 1, -1, -1):
        if llm_request.contents[i].role == "user":
            insert_idx = i
            break

    llm_request.contents.insert(insert_idx, context_content)


context_text_form = """
=== CURRENT DATA OF {{section_name}} ===
{{data}}
"""


def inject_artifact_context(
    sections: list[str],
    db_repository: BaPackageRepository | None = None,
):
    """Inject artifact section data from Database into LLM context."""

    def callback(callback_context: CallbackContext, llm_request: LlmRequest) -> None:
        ctx_state = callback_context.state
        raw_session_id = ctx_state.get("session_id", "")
        select_agent = ctx_state.get("select_agent", "")
        session_id = extract_session_id(raw_session_id, select_agent)

        if not session_id:
            return

        repo = db_repository or BaPackageRepository()

        for section_name in sections:
            section_data = repo.get_section(session_id, section_name)

            # Nếu DB chưa có bản ghi -> Tự động khởi tạo data rỗng {} trong DB
            if section_data is None:
                section_data = {}
                repo.save_section(
                    session_id=session_id,
                    section_id=section_name,
                    data=section_data,
                    flags={},
                    is_completable=False,
                )

            # Đọc nội dung file ngẫu nhiên (On-the-fly) nếu có đường dẫn file
            if isinstance(section_data, dict):
                section_data_copy = dict(section_data)

                # Kiểm tra workflow_md_path
                if "workflow_md_path" in section_data_copy:
                    path_str = section_data_copy["workflow_md_path"]
                    if isinstance(path_str, str) and path_str.strip():
                        file_p = Path(path_str.strip())
                        if file_p.exists():
                            section_data_copy["workflow_md_content"] = file_p.read_text(
                                encoding="utf-8"
                            )

                # Kiểm tra bpmn_xml_path
                if "bpmn_xml_path" in section_data_copy:
                    path_str = section_data_copy["bpmn_xml_path"]
                    if isinstance(path_str, str) and path_str.strip():
                        file_p = Path(path_str.strip())
                        if file_p.exists():
                            section_data_copy["bpmn_xml_content"] = file_p.read_text(
                                encoding="utf-8"
                            )

                data = json.dumps(section_data_copy, ensure_ascii=False)
            else:
                data = json.dumps(section_data, ensure_ascii=False)

            context_text = format_string(
                context_text_form, section_name=section_name, data=data
            )
            insert_context(llm_request, context_text)

    return callback
