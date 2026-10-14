# Design Spec: Tag Change Tracking & Chat Preamble Injection

- **Date:** 2026-08-05
- **Status:** Approved
- **Scope:** Frontend (Live Form Editor & Chat UI integration) & DB Persistence Behavior

---

## 1. Overview & Business Value

Khi người dùng thao tác trực tiếp trên giao diện **Live Form Editor** (thêm/xóa các tag thuộc tính `actors`, `scope_in`, `scope_out`), hệ thống cần:
1. Ghi lại các thao tác điều chỉnh thủ công này vào một hàng đợi chờ gửi (`pendingEdits`).
2. Hiển thị một **Banner "Thay đổi chờ gửi"** (Explicit Queue Banner) trực quan ngay trên khung nhập tin nhắn Chat.
3. Tự động đính kèm thông báo tổng hợp điều chỉnh vào **đầu tin nhắn** (Preamble Injection) khi người dùng bấm gửi tin nhắn mới cho Interactive Discussion Agent.

---

## 2. DB Persistence & Reset Mechanics (Xử lý DB & Reset)

### 2.1 Khi nào Database (DB) được cập nhật?
- **Khi bấm nút xóa/thêm tag trên Form**: DB **CHƯA** bị thay đổi ngay lập tức. Thao tác chỉ lưu tạm thời trên mảng `pendingEdits` của Frontend và giao diện Form phản ánh trước cho user thấy.
- **Khi bấm Gửi tin nhắn**: Tin nhắn kèm Preamble được gửi tới backend. `artifact_extractor` sẽ trích xuất danh sách mới (VD: danh sách `actors` đã loại bỏ "con người"), ủy thác cho `ArtifactManager` ghi đè danh sách mới này vào Database, đồng thời tính toán lại `flags` và `MISSING_VALUES`.

### 2.2 Các kịch bản Reset

1. **Kịch bản 1: Người dùng bấm "✕ Hủy tất cả" trên Banner**
   - Mảng `pendingEdits` bị xóa sạch (`[]`).
   - Giao diện Live Form Editor được re-render khôi phục lại dữ liệu gốc lấy từ DB.
   - Banner ẩn đi. DB giữ nguyên không bị ảnh hưởng.

2. **Kịch bản 2: Người dùng bấm Reset Section (Khôi phục ban đầu)**
   - Toàn bộ dữ liệu section (Goal, Actors, Scope In, Scope Out) bị xóa về trạng thái trống (`{}`).
   - Mảng `pendingEdits` bị clear (`[]`).
   - Form Editor cập nhật về trống, Banner ẩn đi, DB lưu lại state rỗng `{}` và `MISSING_VALUES` sẽ kích hoạt lại tất cả các trường required.

---

## 3. Component Architecture & Data Flow

### 3.1 State Data Structure (`pendingEdits`)

Mỗi khi người dùng thêm hoặc xóa một tag thủ công trên Form, một đối tượng `PendingEdit` được đẩy vào mảng `pendingEdits` trên Frontend:

```typescript
interface PendingEdit {
  id: string;          // Unique ID, e.g. "edit_1785895789614"
  type: "ADD" | "REMOVE";
  field: "actors" | "scope_in" | "scope_out" | "goal";
  value: string;       // e.g. "con người"
  timestamp: number;
}
```

### 3.2 User Interaction Flow

```
[User Form Interaction] ──(Click Xóa/Thêm Tag)──> [Push to pendingEdits Array]
                                                          │
                                                          ▼
                                              [Render Amber Banner on Chat UI]
                                                          │
                                     ┌────────────────────┴────────────────────┐
                                     ▼                                         ▼
                            (User Clicks "Hủy")                       (User Clicks Send Message)
                                     │                                         │
                        [Clear pendingEdits Queue]              [Build Preamble + Append User Msg]
                                     │                                         │
                                [Hide Banner]                          [Send Payload to Agent API]
                                     │                                         │
                         [Restore Form from DB]                    [ArtifactManager Updates DB]
                                                                               │
                                                                       [Clear Queue & Hide Banner]
```

---

## 4. Detailed UI Design & Formatting Rules

### 4.1 Banner UI Specifications

- **Vị trí**: Nằm ngay phía trên khung nhập tin nhắn (`#chat-input-container`).
- **Phong cách (Dark Mode)**:
  - Background: `rgba(245, 158, 11, 0.1)` (Amber tint).
  - Border: `1px solid rgba(245, 158, 11, 0.3)`.
  - Icon: ⚡ (Amber glow).
  - Content: Hiển thị danh sách tóm tắt các thao tác đang chờ gửi (bullet points).
  - Control: Nút `✕ Hủy tất cả` (Rose tint) để hủy bỏ hàng đợi.

### 4.2 Prompt Preamble Template

Khi gửi tin nhắn, nếu `pendingEdits.length > 0`:

```text
Tôi đã có điều chỉnh thủ công:
- Xóa "con người" ra khỏi "actors" - bạn không cần làm gì thêm
- Thêm "Thanh toán QR" vào "scope_in" - bạn không cần làm gì thêm

[Nội dung tin nhắn thực tế của người dùng]
```

---

## 5. Testing & Verification Plan

### 5.1 Manual Scenario Verification
1. **Xóa 1 Tag**: Xóa "con người" khỏi `actors` → Banner xuất hiện hiển thị 1 dòng. Gửi tin nhắn → Verify DB được cập nhật đè danh sách mới.
2. **Thao tác nhiều tag**: Xóa 1 actor, thêm 1 scope_in → Banner hiển thị 2 dòng.
3. **Hủy hàng đợi**: Click nút "Hủy tất cả" → Banner biến mất, Form reset về dữ liệu DB cũ, gửi tin nhắn bình thường không có preamble.
