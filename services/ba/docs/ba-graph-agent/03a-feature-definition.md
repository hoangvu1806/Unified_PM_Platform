# Feature Definition Node — Thiết kế chi tiết

> **Trạng thái**: vision (2026-08-06). Runtime extractor / flags / discussion (+ OQ/ASM on FD) is in `agents/sub_graph/feature_definition/`.

---

## 1. Tổng quan & Kiến trúc ADK Workflow

Feature Definition Node xử lý mô tả tự do từ User, trích xuất ra structured data (goal, actors, scope_in, scope_out), đồng thời tự động phát hiện Open Questions (OQ) và Assumptions (ASM) ở Tầng 2.

### Cấu trúc ADK Workflow: Parallel Fan-Out / Fan-In (với `JoinNode`)

```
User Message
     │
     ▼
  ROUTER Node
     │
     ├───► [FD Extractor (LLM)] ────► [FD Flags Checker (Function)] ──┐ (Branch 1)
     │                                                                │
     │                                                                ├─► [JoinNode] ─► [FD Discussion (LLM)]
     │                                                                │
     └───► [OQ & ASM Detector (LLM)] ─────────────────────────────────┘ (Branch 2 - Shared Node)
```

### Nguyên lý vận hành:
1. **Parallel Fan-Out**: Khi Router route tới `"fd"`, 2 nhánh được kích hoạt chạy song song:
   - **Branch 1**: `FD Extractor` trích xuất delta FD → `FD Flags Checker` đánh giá completion flags.
   - **Branch 2**: `OQ & ASM Detector` (Node dùng chung) quét tin nhắn tìm OQ/ASM phát sinh.
2. **Fan-In Join (`JoinNode`)**: Giữ luồng chờ cả 2 nhánh chạy xong và ghi nhận dữ liệu mới vào `ctx.state`.
3. **Discussion Output**: `FD Discussion` đọc toàn bộ State (FD Artifact, Completion Flags, OQ & Assumptions vừa phát hiện) để tổng hợp câu trả lời tự nhiên và đầy đủ nhất cho User.

---

## 2. Schema & State

### 2.1 Output Schema — `FeatureDefinitionData` (Extractor)

```python
from pydantic import BaseModel, Field
from typing import Optional


class FeatureDefinitionData(BaseModel):
    """Schema cho FD Extractor output. LLM trả về delta mỗi turn."""

    goal: Optional[str] = Field(
        None,
        description="WHY feature này cần tồn tại — business value cụ thể. "
                    "Chỉ cập nhật khi User cung cấp thông tin mới về mục tiêu."
    )
    actors: Optional[list[str]] = Field(
        None,
        description="Danh sách actors liên quan (format: 'ACT-NAME: mô tả vai trò'). "
                    "Gộp actors mới vào danh sách hiện tại, KHÔNG xóa actors cũ."
    )
    scope_in: Optional[list[str]] = Field(
        None,
        description="Capabilities thuộc phạm vi feature. "
                    "Thêm mới vào danh sách hiện tại."
    )
    scope_out: Optional[list[str]] = Field(
        None,
        description="Capabilities KHÔNG thuộc phạm vi. "
                    "Thêm mới vào danh sách hiện tại."
    )
```

### 2.2 Output Schema — `OQASMDetectionData` (Detector dùng chung)

```python
class OpenQuestionItem(BaseModel):
    id: Optional[str] = Field(None, description="Tự động sinh OQ-XXX")
    question: str = Field(..., description="Câu hỏi kết thúc bằng dấu ?")
    severity: str = Field("warning", description="critical | warning | info")
    assigned_to: str = Field("PO", description="PO | Tech Lead | BA | Designer")
    impact: str = Field(..., description="Mô tả ảnh hưởng")

class AssumptionItem(BaseModel):
    id: Optional[str] = Field(None, description="Tự động sinh ASM-XX")
    statement: str = Field(..., description="Giả định cụ thể, có thể verify/invalidate")

class OQASMDetectionData(BaseModel):
    """Schema cho OQ & ASM Detector output."""
    open_questions: list[OpenQuestionItem] = Field(default_factory=list)
    assumptions: list[AssumptionItem] = Field(default_factory=list)
```

### 2.3 State Structure (`ctx.state`)

```python
{
    "active_section": "feature_definition",
    "artifacts": {
        "feature_definition": {
            "goal": "Cho phép khách hàng thanh toán qua ví điện tử...",
            "actors": ["ACT-CUSTOMER: Khách hàng mua sắm", "ACT-PAYMENT-GW: Hệ thống thanh toán"],
            "scope_in": ["Thanh toán qua MoMo", "Thanh toán qua ZaloPay"],
            "scope_out": ["Ví nội bộ"]
        }
    },
    "flags": {
        "fd": {
            "FD-F1": {"status": "PASS", "detail": None},
            "FD-F2": {"status": "PASS", "detail": None},
            "FD-F3": {"status": "PASS", "detail": None},
            "FD-F4": {"status": "WARNING", "detail": "scope_out[] đang trống"},
            "FD-F5": {"status": "PASS", "detail": None}
        }
    },
    "open_questions": [
        {
            "id": "OQ-001",
            "question": "Hạn mức nạp tối đa qua MoMo 1 ngày là bao nhiêu?",
            "severity": "critical",
            "status": "open",
            "assigned_to": "PO",
            "source_section": "feature_definition",
            "source_turn": 1
        }
    ],
    "assumptions": [
        {
            "id": "ASM-01",
            "statement": "Hệ thống đã tích hợp sẵn API Gateway kết nối MoMo SDK",
            "source_section": "feature_definition",
            "source_turn": 1
        }
    ],
    "sections_status": {
        "feature_definition": "in_progress"  # → "completed" khi tất cả Blocker flags PASS
    }
}
```

---

## 3. Các Component Chi Tiết trong Workflow

### 3.1 Nhánh 1a: FD Extractor (LlmAgent)

- **Input**: User message + `ctx.state["artifacts"]["feature_definition"]`.
- **Output**: `FeatureDefinitionData` (Pydantic).
- **Callback (`fd_merge_callback`)**: Merge các trường non-null vào state.

```python
async def fd_merge_callback(callback_context, llm_response):
    """Merge delta output vào artifact hiện tại trong state."""
    delta = llm_response.parsed  # FeatureDefinitionData
    state = callback_context.state
    
    current = state.setdefault("artifacts", {}).setdefault("feature_definition", {})
    
    if delta.goal is not None:
        current["goal"] = delta.goal
    if delta.actors is not None:
        current["actors"] = delta.actors
    if delta.scope_in is not None:
        current["scope_in"] = delta.scope_in
    if delta.scope_out is not None:
        current["scope_out"] = delta.scope_out
```

### 3.2 Nhánh 1b: FD Flags Checker (FunctionNode)

Kích hoạt ngay sau khi `fd_extractor` hoàn tất merge dữ liệu.

```python
@node(name="fd_flags_checker")
def fd_flags_checker_node(ctx: Context) -> dict:
    """FunctionNode — đánh giá 5 completion flags cho Feature Definition."""
    fd = ctx.state.get("artifacts", {}).get("feature_definition", {})
    flags = {}
    
    # FD-F1: Goal defined
    goal = fd.get("goal", "")
    flags["FD-F1"] = {
        "status": "PENDING_SEMANTIC" if (goal and goal.strip()) else "FAIL",
        "detail": "Goal chưa được xác định" if not goal else "Cần kiểm tra business value"
    }
    
    # FD-F2: Actors ≥ 2
    actors = fd.get("actors", [])
    flags["FD-F2"] = {
        "status": "PASS" if len(actors) >= 2 else "FAIL",
        "detail": None if len(actors) >= 2 else f"Cần ≥ 2 actors, hiện có {len(actors)}"
    }
    
    # FD-F3: Scope In ≥ 1
    scope_in = fd.get("scope_in", [])
    flags["FD-F3"] = {
        "status": "PASS" if len(scope_in) >= 1 else "FAIL",
        "detail": None if len(scope_in) >= 1 else "Scope In chưa có item nào"
    }
    
    # FD-F4: Scope Out ≥ 1 (Warning)
    scope_out = fd.get("scope_out", [])
    flags["FD-F4"] = {
        "status": "PASS" if len(scope_out) >= 1 else "WARNING",
        "detail": None if len(scope_out) >= 1 else "Scope Out trống — nên bổ sung để tránh scope creep"
    }
    
    # FD-F5: No scope conflict
    flags["FD-F5"] = {
        "status": "PENDING_SEMANTIC" if (scope_in and scope_out) else "PASS",
        "detail": "Cần kiểm tra mâu thuẫn scope" if (scope_in and scope_out) else "Chưa đủ data để conflict"
    }
    
    ctx.state.setdefault("flags", {})["fd"] = flags
    return flags
```

### 3.3 Nhánh 2: OQ & ASM Detector (LlmAgent - Shared Node)

Chạy **song song** với Nhánh 1 từ lúc bắt đầu turn.

```python
async def oq_asm_merge_callback(callback_context, llm_response):
    """Callback lưu OQ và Assumptions mới phát hiện vào State."""
    detected = llm_response.parsed  # OQASMDetectionData
    state = callback_context.state
    current_turn = state.get("current_turn", 1)
    active_sec = state.get("active_section", "feature_definition")
    
    # Merge Open Questions
    if detected.open_questions:
        oqs = state.setdefault("open_questions", [])
        start_idx = len(oqs) + 1
        for i, item in enumerate(detected.open_questions):
            oqs.append({
                "id": f"OQ-{start_idx + i:03d}",
                "question": item.question,
                "severity": item.severity,
                "status": "open",
                "impact": item.impact,
                "answer": None,
                "assigned_to": item.assigned_to,
                "source_section": active_sec,
                "source_turn": current_turn
            })
            
    # Merge Assumptions
    if detected.assumptions:
        asms = state.setdefault("assumptions", [])
        start_idx = len(asms) + 1
        for i, item in enumerate(detected.assumptions):
            asms.append({
                "id": f"ASM-{start_idx + i:02d}",
                "statement": item.statement,
                "source_section": active_sec,
                "source_turn": current_turn
            })
```

### 3.4 FD Discussion (LlmAgent - Target sau JoinNode)

Được kích hoạt sau khi `JoinNode` xác nhận cả 2 nhánh đã hoàn thành.

#### System Prompt (Flexible & Natural Language Protocol)
```
Bạn là BA Agent chuyên nghiệp đồng hành cùng User trong khâu định nghĩa tính năng (Feature Definition).

## Phong cách Trao đổi (Natural & Flexible):
- Nói chuyện tự nhiên, ngắn gọn như một Senior BA.
- TUYỆT ĐỐI KHÔNG sử dụng các mã kỹ thuật như FD-F1, FD-F2, FD-F3, FD-F4, FD-F5 trong câu trả lời. Hãy diễn đạt hoàn toàn bằng ngôn ngữ tự nhiên nghiệp vụ (Mục tiêu kinh doanh, Đối tượng sử dụng, Phạm vi thực hiện...).
- KHÔNG đóng khung rập khuôn theo các mục 1, 2, 3, 4 nếu không cần thiết. Linh hoạt phản hồi theo mạch hội thoại của User.

## Thứ tự Ưu tiên Thông tin (Priority P1 -> P5):
1. P1 (Mục tiêu kinh doanh - Goal): QUAN TRỌNG NHẤT. Nếu mục tiêu chưa rõ lý do kinh doanh (WHY), ưu tiên gợi ý 2-3 mục tiêu mẫu cụ thể (ví dụ: tăng tỷ lệ chuyển đổi X%, giảm thời gian Y...).
2. P2 (Đối tượng sử dụng - Actors): Nếu danh sách chưa đủ (ít hơn 2 actors), gợi ý các vai trò hoặc hệ thống tham gia phổ biến.
3. P3 (Phạm vi thực hiện - Scope In): Gợi ý các tính năng cốt lõi.
4. P4 (Mâu thuẫn phạm vi - Scope Conflict): Chỉ ra vị trí mâu thuẫn giữa Scope In và Scope Out nếu có.
5. P5 (Phạm vi loại trừ - Scope Out): Nhắc nhẹ bổ sung để tránh scope creep.

## Nhiệm vụ Phản hồi:
- Trả lời thắc mắc / thảo luận của User (nếu User đặt câu hỏi).
- Tóm tắt ngắn gọn thông tin vừa ghi nhận.
- Nhắm trực tiếp vào mục THIẾU có PRIORITY CAO NHẤT, đưa ra 2-3 gợi ý cụ thể để User chọn lựa hoặc tinh chỉnh.
- Nếu có Câu hỏi mở (Open Questions) hoặc Giả định (Assumptions) mới, lồng ghép tự nhiên vào lời văn.
- Khi TẤT CẢ các thông tin quan trọng đã đầy đủ, chúc mừng User và chủ động đề xuất chuyển sang bước tiếp theo (Quy tắc nghiệp vụ - Business Rules).
```

---

## 4. Code Implementation Mẫu chuẩn Google ADK

```python
from config.model_config import base_model
from google.adk.agents import LlmAgent
from google.adk.workflow import Workflow, JoinNode, node, Context

# 1. Các Agents & Nodes
fd_extractor_node = LlmAgent(
    name="fd_extractor",
    model=base_model,
    instruction=FD_EXTRACTOR_INSTRUCTION,
    output_schema=FeatureDefinitionData,
    after_model_callback=fd_merge_callback
)

oq_asm_detector_node = LlmAgent(
    name="oq_asm_detector",
    model=base_model,
    instruction=OQ_ASM_DETECTOR_INSTRUCTION,
    output_schema=OQASMDetectionData,
    after_model_callback=oq_asm_merge_callback
)

fd_discussion_node = LlmAgent(
    name="fd_discussion",
    model=base_model,
    instruction=FD_DISCUSSION_INSTRUCTION,
    after_model_callback=fd_semantic_flags_callback
)

# 2. JoinNode kết nối Fan-In
join_node = JoinNode(name="fd_fan_in_join")

# 3. Workflow Subgraph định nghĩa edges
fd_subgraph = Workflow(
    name="fd_section_workflow",
    edges=[
        # Fan-Out song song ngay từ START: Extractor và OQ/ASM Detector
        ('START', (fd_extractor_node, oq_asm_detector_node)),
        
        # Nhánh 1 nối tiếp: Extractor -> Flags Checker
        (fd_extractor_node, fd_flags_checker_node),
        
        # Fan-In Join: Chờ cả Flags Checker và OQ/ASM Detector xong
        ((fd_flags_checker_node, oq_asm_detector_node), join_node),
        
        # Kích hoạt Discussion
        (join_node, fd_discussion_node),
    ]
)
```

---

## 5. Ví dụ Luồng Hoạt Động (Turn-by-Turn)

### Turn 1: User gửi tin nhắn mơ hồ
**User**: *"Tôi muốn thêm thanh toán MoMo và ZaloPay. Giả sử hệ thống đã tích hợp sẵn API Gateway. Hạn mức nạp tối đa chưa rõ để tôi hỏi lại PO."*

#### Diễn biến trong Graph:
1. **Parallel Execution**:
   - `fd_extractor`: Trích xuất `scope_in = ["Thanh toán MoMo", "Thanh toán ZaloPay"]`.
   - `oq_asm_detector`:
     - Phát hiện OQ: `"Hạn mức nạp tối đa qua MoMo/ZaloPay là bao nhiêu?"` (severity: `critical`) → Tạo `OQ-001`.
     - Phát hiện ASM: `"Hệ thống đã tích hợp sẵn API Gateway"` → Tạo `ASM-01`.
2. `fd_flags_checker`: Đánh giá FD-F2 (Actors < 2) ❌ FAIL, FD-F3 (Scope In) ✅ PASS.
3. `JoinNode`: Đợi 2 nhánh hoàn thành và đồng bộ dữ liệu vào `ctx.state`.
4. `fd_discussion`: Tổng hợp toàn bộ context từ State và phản hồi.

#### Response hiển thị cho User:
> Tôi đã ghi nhận tính năng thanh toán qua MoMo và ZaloPay.
>
> 📋 **Trạng thái Feature Definition:**
> - ✅ **Scope In**: 2 items
> - ❌ **FD-F2 (Actors)**: Chưa xác định actors (Cần tối thiểu 2 actors).
> - ⚠️ **FD-F1 (Goal)**: Chưa rõ mục tiêu kinh doanh (WHY).
>
> 📌 **Ghi nhận Tầng 2 (Real-time):**
> - ❓ **Open Question (OQ-001)**: Hạn mức nạp tối đa qua MoMo/ZaloPay là bao nhiêu? (Gán cho: PO)
> - 💡 **Assumption (ASM-01)**: Hệ thống đã tích hợp sẵn API Gateway.
>
> Bạn vui lòng bổ sung thêm **Goal (mục tiêu kinh doanh)** và các **Actors** nhé!
