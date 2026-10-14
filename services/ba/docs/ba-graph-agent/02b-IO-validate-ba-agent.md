# BA Agent — Validation A2A: I/O Contract

> **Trạng thái**: vision (August 2026). **Runtime September 2026:** Validate is an **in-process subgraph** on the same ADK runner — not HTTP A2A. See [DESIGN.md](../../DESIGN.md) and [README.md](README.md).
> **Ngày**: 2026-08-06  
> **Nguồn**: Brainstorming session — Validation A2A + I/O Contract  
> **Xem thêm**: Feature Status Lifecycle → [02a-feature-status.md](02a-feature-status.md)

---

## 1. Validation A2A Flow

### Luồng chính

```
User bấm [Validate]
    │
    ▼
BA Agent Router → route = "validate"
    │
    ▼
Validate Proxy Node (FunctionNode, KHÔNG dùng LLM)
    │
    ├── Thu thập từ ctx.state:
    │   • artifacts (toàn bộ 8 sections data)
    │   • flags (completion flags)
    │   • ticket_type
    │   • sections_status
    │   • open_questions[]
    │   • assumptions[]
    │
    ├── Gọi A2A (= API call) → Validate Agent
    │       │
    │       ▼
    │   Validate Agent xử lý:
    │       • Check change detection (so với lần validate trước)
    │       • Nếu KHÔNG thay đổi → trả "no_change" + status cũ
    │       • Nếu CÓ thay đổi → validate full → trả passed/failed + report
    │
    ├── Nhận A2A Response
    │
    ├── Cập nhật ctx.state["feature_status"]:
    │   • "passed"    → VALIDATED
    │   • "failed"    → VALIDATION_FAILED
    │   • "no_change" → giữ nguyên, thông báo
    │
    └── Return validation_report làm output của Node
        → Đây chính là message trả về User (pass-through, KHÔNG qua LLM)
        → Tự động nằm trong conversation history
        → Turn sau BA Agent tự thấy (không cần inject riêng)
```

### Validate Proxy Node (Pseudo-code)

```python
async def validate_proxy_node(ctx: Context):
    """FunctionNode — NO LLM. API call + pass-through."""
    
    # 1. Thu thập data từ state
    payload = {
        "ticket_type": ctx.state.get("ticket_type", "NEW_FEATURE"),
        "artifacts": ctx.state.get("artifacts", {}),
        "sections_status": ctx.state.get("sections_status", {}),
        "open_questions": ctx.state.get("open_questions", []),
        "assumptions": ctx.state.get("assumptions", []),
        "flags": ctx.state.get("flags", {}),
    }
    
    # 2. Gọi Validate Agent qua A2A (= API call)
    result = await validate_agent_api.call(payload)
    
    # 3. Xử lý no_change
    if result["status"] == "no_change":
        return f"📋 Chưa có thay đổi. Tình trạng: **{ctx.state.get('feature_status')}**"
    
    # 4. Cập nhật feature status trong state
    ctx.state["feature_status"] = (
        "VALIDATED" if result["status"] == "passed" 
        else "VALIDATION_FAILED"
    )
    
    # 5. Return report làm output → message cho User
    #    (tự động vào conversation history, không cần inject)
    return result["report"]
```

---

## 2. Post-Validation: BA Agent hỗ trợ fix khi VALIDATION_FAILED

```
VALIDATION_FAILED
    │
    ├── Validation report đã nằm trong conversation history
    │   (là output của Validate Proxy Node ở turn trước)
    │
    ├── User tiếp tục chat → BA Agent tự thấy report trong history
    │   → Hỗ trợ sửa artifact tương ứng
    │   → Thông báo "Đã cập nhật section X theo yêu cầu"
    │
    ├── Status vẫn giữ VALIDATION_FAILED
    │   (không đổi cho đến khi re-validate)
    │
    ├── Nút Validate vẫn ENABLED
    │
    └── User bấm Validate lại → Validate Proxy → A2A
        → passed → VALIDATED
        → failed → VALIDATION_FAILED (tiếp tục fix)
```

---

## 3. Change Detection (Validate Agent's Responsibility)

| Scenario | Validate Agent xử lý | BA Agent nhận |
|----------|---------------------|---------------|
| Artifacts **không thay đổi** từ lần validate trước | So sánh snapshot → trả `"no_change"` | Thông báo: "Chưa có thay đổi. Tình trạng: [status]" |
| Artifacts **có thay đổi** | Validate lại toàn bộ → trả `"passed"` / `"failed"` | Cập nhật feature_status + hiện report |
| Lần **đầu tiên** validate | Chưa có snapshot → validate full | Cập nhật feature_status + hiện report |

> **Lưu ý**: BA Agent KHÔNG cần implement change detection. BA Agent luôn gửi full payload. Validate Agent tự quản lý snapshot và so sánh.

---

## 4. Validate Agent — Input / Output Contract

### Input (BA Agent gửi qua A2A)

```json
{
  "ticket_type": "NEW_FEATURE",
  "artifacts": {
    "feature_definition": { "..." },
    "business_rules": [ "..." ],
    "workflow": { "..." },
    "use_cases": [ "..." ],
    "bpmn_reference": { "..." },
    "ui_touchpoints": [ "..." ],
    "open_questions": [ "..." ],
    "assumptions": [ "..." ]
  },
  "sections_status": {
    "feature_definition": "completed",
    "business_rules": "completed",
    "workflow": "completed",
    "use_cases": "completed",
    "bpmn_reference": "completed",
    "ui_touchpoints": "skipped",
    "open_questions": "active",
    "assumptions": "active"
  },
  "flags": {
    "FD-F1": "PASS",
    "BR-F1": "PASS",
    "UC-F1": "PASS",
    "...": "..."
  }
}
```

### Output (Validate Agent trả về)

```json
{
  "status": "passed | failed | no_change",
  "agent_response": "string — BA Agent dùng trực tiếp làm response cho User",
  "failed_checks": [
    {
      "check_id": "V-05",
      "name": "UC-WF alignment",
      "severity": "error | warning",
      "detail": "US-02 tham chiếu WF Step 3 nhưng Step 3 đã bị xóa",
      "suggestion": "Cập nhật US-02 hoặc khôi phục WF Step 3",
      "affected_sections": ["use_cases", "workflow"]
    }
  ],
  "warnings": [
    {
      "check_id": "V-08",
      "name": "Actor completeness",
      "detail": "Actor ACT-RECONCILIATION chưa có UC nào",
      "suggestion": "Thêm Use Case cho actor này"
    }
  ],
  "change_detected": true,
  "validated_at": "2026-08-06T08:55:00+07:00"
}
```

> **`agent_response`**: Validate Agent tổng hợp kết quả thành câu trả lời tự nhiên. BA Agent dùng trực tiếp làm message trả về User (pass-through, KHÔNG interpret lại bằng LLM).  
> **`failed_checks`** và **`warnings`**: Chỉ có khi `status = "failed"`. Khi `status = "passed"` → cả hai đều `[]`.

> **Lưu ý**: Validate Agent tự quản lý snapshot để change detection. BA Agent luôn gửi full payload, không cần biết snapshot là gì.

---

## 5. Ví dụ I/O — Feature "Payment Wallet Integration"

### Input chung (BA Agent gửi — dùng cho cả 3 ví dụ)

```json
{
  "ticket_type": "NEW_FEATURE",
  "artifacts": {
    "feature_definition": {
      "goal": "Cho phép khách hàng thanh toán qua ví điện tử MoMo/ZaloPay để giảm tỷ lệ bỏ giỏ hàng",
      "actors": ["ACT-CUSTOMER", "ACT-PAYMENT-GW", "ACT-WALLET-PROVIDER"],
      "scope_in": ["Thanh toán qua MoMo", "Thanh toán qua ZaloPay", "Hoàn tiền về ví"],
      "scope_out": ["Thanh toán qua thẻ tín dụng", "Ví nội bộ"]
    },
    "business_rules": [
      {"id": "BR-01", "statement": "Khi đơn hàng ≥ 500,000 VND, hệ thống yêu cầu xác thực OTP từ ví", "source": "Security"},
      {"id": "BR-02", "statement": "Khi thanh toán thất bại sau 3 lần retry, hệ thống hủy giao dịch và hoàn tiền trong 24h", "source": "Policy"}
    ],
    "workflow": "## Main Flow\n| Step | Actor | Action | BR Ref |\n|------|-------|--------|--------|\n| 1 | ACT-CUSTOMER | Chọn ví MoMo/ZaloPay | - |\n| 2 | ACT-PAYMENT-GW | Gửi request tới wallet provider | - |\n| 3 | ACT-WALLET-PROVIDER | Xác thực OTP | BR-01 |\n| 4 | ACT-PAYMENT-GW | Xác nhận thanh toán thành công | - |\n\n## Exception Flows\n| ID | Condition | Handling |\n|----|-----------|----------|\n| E-01 | Thanh toán thất bại sau 3 lần | Hủy giao dịch, hoàn tiền 24h (BR-02) |\n\n## End States\n- END-PAID: Thanh toán thành công\n- END-CANCELLED: Giao dịch bị hủy",
    "use_cases": [
      {
        "id": "US-01",
        "actor_id": "ACT-CUSTOMER",
        "statement": "Là khách hàng, tôi muốn thanh toán qua MoMo để không cần nhập thẻ mỗi lần mua.",
        "rule_ids": ["BR-01"],
        "acceptance_criteria": [
          {"id": "AC-01", "given": "Đơn hàng ≥ 500k VND", "when": "Khách chọn MoMo", "then": "Hệ thống yêu cầu OTP"}
        ]
      }
    ]
  },
  "sections_status": {
    "feature_definition": "completed",
    "business_rules": "completed",
    "workflow": "completed",
    "use_cases": "completed"
  },
  "flags": {
    "FD-F1": "PASS", "FD-F2": "PASS", "FD-F3": "PASS", "FD-F4": "PASS", "FD-F5": "PASS",
    "BR-F1": "PASS", "BR-F2": "PASS",
    "UC-F1": "PASS", "UC-F2": "PASS", "UC-F3": "PASS", "UC-F7": "PASS"
  }
}
```

---

### 5.1 Ví dụ: Validate PASSED ✅

**Scenario**: Tất cả sections hoàn tất, data nhất quán giữa FD ↔ BR ↔ WF ↔ UC.

**Output**:
```json
{
  "status": "passed",
  "agent_response": "✅ Feature \"Payment Wallet Integration\" đã hoàn toàn hợp lệ. Tất cả cross-section checks đều passed (FD↔BR, BR↔WF, WF↔UC). Feature sẵn sàng để export lên hệ thống và chuyển sang giai đoạn Design.",
  "failed_checks": [],
  "warnings": [],
  "change_detected": true,
  "validated_at": "2026-08-06T09:30:00+07:00"
}
```

**→ BA Agent**: Dùng `agent_response` trực tiếp làm message trả về User. Cập nhật `feature_status = "VALIDATED"`, enable nút Export (push lên HULY).

---

### 5.2 Ví dụ: Validate FAILED ❌

**Scenario**: User đã xóa WF Step 3 (OTP) mà chưa cập nhật UC/BR tương ứng → mâu thuẫn cross-section.

**Output**:
```json
{
  "status": "failed",
  "agent_response": "❌ Validation không đạt. Phát hiện 2 lỗi nghiêm trọng và 1 cảnh báo:\n\n**Lỗi 1 (BR-WF traceability):** BR-01 yêu cầu 'xác thực OTP từ ví' nhưng không có bước nào trong Workflow tham chiếu BR-01. Gợi ý: Thêm lại bước OTP vào Workflow hoặc cập nhật BR-01.\n\n**Lỗi 2 (UC-WF alignment):** AC-01 mô tả 'Hệ thống yêu cầu OTP' nhưng Workflow không còn bước OTP nào. Gợi ý: Cập nhật AC-01 hoặc khôi phục bước OTP trong Workflow.\n\n**Cảnh báo:** Workflow chỉ có 1 exception flow (E-01). Feature thanh toán thường cần ≥ 2 (timeout, insufficient balance).\n\nVui lòng sửa các lỗi trên và bấm Validate lại.",
  "failed_checks": [
    {
      "check_id": "V-02",
      "name": "BR-WF traceability",
      "severity": "error",
      "detail": "BR-01 yêu cầu 'xác thực OTP từ ví' nhưng không có bước nào trong Workflow tham chiếu BR-01",
      "suggestion": "Thêm lại bước OTP vào Workflow hoặc cập nhật BR-01",
      "affected_sections": ["business_rules", "workflow"]
    },
    {
      "check_id": "V-05",
      "name": "UC-WF alignment",
      "severity": "error",
      "detail": "AC-01 mô tả 'Hệ thống yêu cầu OTP' nhưng Workflow không còn bước OTP nào",
      "suggestion": "Cập nhật AC-01 hoặc khôi phục bước OTP trong Workflow",
      "affected_sections": ["use_cases", "workflow"]
    }
  ],
  "warnings": [
    {
      "check_id": "V-07",
      "name": "Exception flow coverage",
      "detail": "Workflow chỉ có 1 exception flow (E-01). Feature thanh toán thường cần ≥ 2 (timeout, insufficient balance)",
      "suggestion": "Xem xét thêm exception flow cho timeout kết nối ví và số dư không đủ"
    }
  ],
  "change_detected": true,
  "validated_at": "2026-08-06T09:35:00+07:00"
}
```

**→ BA Agent**: Dùng `agent_response` trực tiếp làm message. Cập nhật `feature_status = "VALIDATION_FAILED"`. Turn sau User chat "sửa lại WF cho tôi" → BA Agent đọc `agent_response` trong history → biết cần thêm lại bước OTP.

---

### 5.3 Ví dụ: Validate NO_CHANGE ⏸️

**Scenario**: User vừa validate PASSED, rồi bấm Validate lại mà không edit gì.

**Output**:
```json
{
  "status": "no_change",
  "agent_response": "📋 Chưa có thay đổi nào từ lần validate trước. Feature hiện tại vẫn ở trạng thái VALIDATED. Bạn có thể bấm Export để đẩy lên hệ thống.",
  "failed_checks": [],
  "warnings": [],
  "change_detected": false,
  "previous_status": "VALIDATED",
  "previous_validated_at": "2026-08-06T09:30:00+07:00"
}
```

**→ BA Agent**: Giữ nguyên `feature_status`, dùng `agent_response` làm message.
