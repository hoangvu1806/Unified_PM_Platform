# Kế hoạch phát triển và triển khai Designer Agent lên production

Ngày lập: 15/09/2026  
Trạng thái: kế hoạch triển khai, chưa phải các tính năng đã hoàn thành.  
Phạm vi: Designer Studio, backend workflow, OpenPencil web/MCP và hạ tầng lưu trữ.

## 1. Mục tiêu và nguyên tắc

Người dùng mở một phiên thiết kế, gửi yêu cầu, xem thiết kế và quay lại sau đó phải tiếp tục được trên đúng tài liệu và đúng tiến độ. Việc refresh trình duyệt, đổi backend replica hoặc thay container OpenPencil không được khiến hệ thống sửa nhầm file hay tự tạo lại toàn bộ dự án.

Đơn vị cấp tài nguyên là **design session/workspace**, không phải container chạy frontend. Một frontend dùng chung có thể phục vụ nhiều người; mỗi workspace đang hoạt động được cấp độc quyền một OpenPencil instance. Khi workspace đang ngủ hoặc đang khôi phục, nó có thể tạm thời chưa có instance sẵn sàng và chưa được phép nhận lệnh chỉnh sửa.

Các điều kiện bắt buộc:

- Một design session có một workspace và một tài liệu thiết kế chính với ID bền vững.
- Một workspace có tối đa một OpenPencil instance được cấp quyền hoạt động tại một thời điểm; instance đó không được phục vụ workspace khác đồng thời.
- Một workspace chỉ có một thao tác ghi đang thực thi, kể cả khi người dùng mở nhiều tab hoặc backend có nhiều worker.
- Backend quyết định endpoint, tài liệu và quyền truy cập. Frontend chỉ gửi session và yêu cầu nghiệp vụ.
- Mọi thao tác đọc cây, render, chụp ảnh, refine và save phải dùng cùng binding đã được xác minh.
- Chỉ báo “đã lưu” khi bản thiết kế và checkpoint tương ứng đã được ghi bền vững.
- Nếu chưa xác minh được tài liệu, hệ thống chuyển sang khôi phục/chờ; không chọn đại tab đang active.

## 2. Hiện trạng đã kiểm tra

Các nhận định dưới đây dựa trên source và DB tại thời điểm lập kế hoạch. Worktree hiện có nhiều thay đổi chưa commit; khi triển khai phải giữ nguyên các thay đổi liên quan đến thiết kế, parser và refine đang có.

| Khu vực | Hiện trạng | Việc cần xử lý |
| --- | --- | --- |
| Session và workflow | SQLite lưu session, run, event, specification và checkpoint | Bổ sung quyền sở hữu, binding runtime và cơ chế khôi phục job |
| Mở lại frontend | `App.tsx` chọn session đầu danh sách sau reload | Đưa session vào URL và bootstrap đúng session |
| Chọn OpenPencil | Endpoint nằm trong `designer.connection` ở localStorage và profile của run | Backend cấp endpoint theo workspace |
| Định danh tài liệu | `document_id` là `tab-N`, sinh lại trong RAM của OpenPencil | Tách ID tài liệu bền vững khỏi ID tab runtime |
| Khôi phục file | Workspace agent thử mở lại bằng path khi `list_pages` lỗi | Xác minh identity ngay cả khi tab ID cũ vẫn tồn tại nhưng thuộc file khác |
| Thực thi run | `RunService` giữ `asyncio.Task` theo run ID trong process | Khóa theo workspace và lưu job để phục hồi sau restart |
| Browser bridge | MCP có một `browserWs`; browser đăng ký mới thay browser cũ | Kiểm soát quyền đăng ký, không cho tab khác chiếm runtime |
| Docker OpenPencil | Có volume `/data`; healthcheck hiện chỉ kiểm tra web trả HTTP thành công | Kiểm tra cả MCP, bridge và tài liệu đã restore |
| Autosave | OpenPencil có autosave và storage binding; document tạo qua MCP browser chưa tự gắn storage binding | Bao phủ cả thay đổi từ agent lẫn người dùng sửa trực tiếp |
| Design system | `/design-systems` liệt kê file cục bộ; `ComponentSource` đọc `source_file` bằng CLI, cache JSX theo fingerprint và đóng gói component cùng dependency | Catalog có phiên bản, quyền truy cập và checksum; resolve file đúng môi trường worker |

Source cần đối chiếu khi thực hiện:

- Designer: `frontend/src/App.tsx`, `frontend/src/connection.ts`, `frontend/src/WorkspacePicker.tsx`.
- Backend: `backend/app/storage/schema.py`, `backend/app/storage/store.py`, `backend/app/workflow/service.py`, `backend/app/workflow/workspace_agent.py`, `backend/app/openpencil/project_executor.py`, `backend/app/openpencil/client.py`.
- Design system: `backend/app/openpencil/components.py`, `backend/app/openpencil/knowledge.py`, route `/design-systems` trong `backend/app/api/routes.py` và volume `DESIGN_DATA_DIR` trong `docker-compose.yml`.
- OpenPencil tại `E:\working\BA\open-pencil`: `src/app/tabs/index.ts`, `src/views/EditorView.vue`, `src/app/automation/bridge/file-handlers.ts`, `packages/mcp/src/browser-rpc.ts`, `compose.yaml`, `Dockerfile`.

Một điểm cần sửa riêng: `_checkpoint_matches_pages` hiện có thể chấp nhận chỉ vì một page ID hoặc tên page trùng, và nhánh mismatch có thể tạo document mới tại cùng output path. Tên như “Design Tokens” không chứng minh đúng tài liệu. Khi recovery, phải đối chiếu document identity, revision và các screen đã hoàn thành; không tự thay file cũ bằng tài liệu rỗng.

## 3. Kiến trúc mục tiêu

```text
Trình duyệt: /sessions/{session_id}
                |
         Gateway có xác thực
                |
          Designer Backend
          /       |       \
  DB metadata   Job worker   Storage .fig + ảnh + tài liệu đầu vào
                    |
           Binding và khóa workspace
                    |
       OpenPencil instance được cấp riêng
         MCP + một editor runtime có quyền ghi
```

Đề xuất cho production: PostgreSQL lưu metadata và hàng đợi công việc ở giai đoạn đầu; S3/MinIO lưu các revision `.fig`, ảnh preview và tài liệu đính kèm. Container giữ bản làm việc trong `/data`. Redis chỉ bổ sung khi có nhu cầu thực tế về điều phối hoặc thông lượng; không cần thêm ngay nếu DB đã đáp ứng khóa và claim job.

Không cần giữ container chạy cho mọi session đã từng tạo. Workspace hết thời gian hoạt động sẽ lưu xong, đóng runtime và trả tài nguyên về pool. Khi quay lại, hệ thống có thể dùng container khác nhưng phải mở đúng revision của cùng tài liệu.

### Editor runtime cần được xác định rõ

Docker hiện tại phục vụ web và MCP; nó chưa tự cung cấp một browser renderer chạy bền vững. Nếu editor đang chạy trong trình duyệt người dùng, refresh/đóng tab vẫn ngắt bridge dù container còn sống.

Lộ trình đầu tiên giữ editor trong trình duyệt người dùng, có lưu liên tục và khôi phục có kiểm soát. Khi tab đóng, job chuyển sang chờ editor và tiếp tục khi kết nối lại. Phải thể hiện giới hạn này rõ trong sản phẩm.

Nếu yêu cầu thiết kế vẫn tiếp tục khi người dùng đóng web, cần thêm browser worker do server quản lý. Đó là phần triển khai riêng: chỉ một editor được ghi, còn giao diện người dùng phải xem cùng runtime hoặc đồng bộ với nó. Không mở đồng thời một browser headless và một editor độc lập vào cùng MCP vì cơ chế đăng ký hiện tại sẽ thay thế kết nối của nhau.

## 4. Dữ liệu và hợp đồng định danh

### Workspace bền vững

| Trường | Mục đích |
| --- | --- |
| `workspace_id` | UUID tồn tại xuyên suốt vòng đời thiết kế |
| `session_id` | Unique; liên kết phiên chat |
| `owner_id` / `tenant_id` | Kiểm tra quyền xem và sửa |
| `document_id` | UUID của tài liệu, độc lập với `tab-N` |
| `document_revision` | Revision đã lưu thành công |
| `storage_key` và `checksum` | Định vị và xác minh nội dung file |
| `last_run_id` | Run liên quan gần nhất; phân biệt run chat với workflow thiết kế |
| `current_screen_id`, `current_page_id` | Vị trí làm việc, có xác minh lại sau import |
| `status` | Provisioning, ready, busy, recovering, sleeping hoặc error |
| `design_system_binding` | Library ID, version, checksum, knowledge/index version và tình trạng nạp thư viện |

### Binding runtime có thể thay đổi

| Trường | Mục đích |
| --- | --- |
| `workspace_id` | Chủ sở hữu binding |
| `instance_id` | Instance được cấp độc quyền |
| `runtime_generation` | Thay đổi khi editor hoặc instance khởi động lại |
| `runtime_document_id` | Tab ID trong generation hiện tại |
| `lease_token`, `lease_expires_at` | Quyền sử dụng có hạn và gia hạn định kỳ |
| `writer_epoch` | Số tăng mỗi lần cấp quyền ghi mới; từ chối worker cũ |

Tách thông tin endpoint nội bộ và secret sang registry của instance. API gửi message/retry/review không nhận endpoint tự do trong chế độ production.

DB cần bảo đảm một binding active cho mỗi workspace và một workspace active cho mỗi instance. Hết lease không có nghĩa được phép cấp ngay một writer mới: phải chặn hoặc dừng writer cũ. MCP/gateway và đường lưu file phải kiểm tra `writer_epoch`, để lệnh đến muộn không thể ghi đè kết quả mới.

Screen registry cần khóa theo `(screen_id, platform)` để một screen có desktop/mobile không ghi đè mapping của nhau. Tên page chỉ hỗ trợ hiển thị và tìm ứng viên, không đủ làm bằng chứng định danh.

## 5. Các luồng cần triển khai

### 5.1. Tạo session và bắt đầu thiết kế

1. Tạo session, workspace và document UUID trong DB bằng thao tác có khóa chống gửi lặp.
2. UI chuyển sang URL của session và hiển thị tài liệu đã được gán. Có thể trì hoãn cấp container đến lúc cần thiết kế để tiết kiệm tài nguyên.
3. Khi workflow cần OpenPencil, claim một instance, cấp lease và chờ bridge sẵn sàng.
4. Resolve design system đã chọn theo phiên bản cố định, kiểm tra file/index/font cần thiết theo mục 5.7. Tạo tài liệu, gắn identity, lưu revision đầu tiên rồi ghi runtime mapping.
5. Workflow dùng binding từ DB cho mọi screen. Component source là tài nguyên đọc riêng, không được trở thành output file.

### 5.2. Build, chỉnh sửa và refine

1. Worker claim job và khóa workspace. Request thứ hai được xếp hàng hoặc phản hồi đang bận.
2. Xác minh owner, instance, generation và document identity trước khi gọi tool.
3. Dùng screen registry để xác định page/root; kiểm tra node thực sự thuộc page đó.
4. Thực hiện thay đổi, inspect và chụp ảnh đúng page. Mỗi screen tối đa hai vòng sửa bằng LLM, sau cùng kiểm tra kết quả.
5. Với screen dài, có ảnh toàn cảnh và các vùng đủ độ phân giải để đọc chữ. Lưu bằng chứng cùng revision được kiểm tra.
6. Lưu revision mới và checkpoint theo quy trình ở mục 6; sau đó phát event cập nhật.

Yêu cầu chat bổ sung tiếp tục chạy trên workspace hiện tại. Không tạo lại toàn bộ specification/JSON của dự án chỉ vì cần thêm hoặc sửa một screen. Trạng thái “đã lưu” và “đã đạt kiểm tra thiết kế” là hai thông tin khác nhau; còn lỗi sau hai vòng refine phải được báo đúng, không giả thành đạt.

### 5.3. Reload Designer Studio hoặc chuyển session

- URL `/sessions/{session_id}` quyết định session đang mở. Nếu session đã xóa hoặc không có quyền, trả trạng thái rõ ràng.
- Bootstrap tải brief, lịch sử, workflow thiết kế liên quan, checkpoint, workspace và trạng thái lưu.
- Bootstrap cũng trả design system đã chọn, phiên bản và trạng thái sẵn sàng; lựa chọn ở session khác không được ghi đè thư viện của session đang mở.
- Tải lịch sử event rồi nối SSE từ sequence phù hợp để không mất hoặc lặp thông báo.
- Hủy hoặc bỏ qua response cũ khi chuyển session. Event của session A không được đổi document picker hoặc artifacts đang hiển thị cho session B.
- Chỉ bật thao tác sửa khi backend xác nhận workspace ready. Picker lấy tài liệu từ binding, không tự ghép alias `tab-N` trong localStorage.

API dự kiến: `GET /sessions/{session_id}/bootstrap` dùng để đọc; `POST /sessions/{session_id}/workspace/activate` dùng khi cần cấp runtime hoặc restore. Các thao tác kích hoạt phải idempotent, gọi lặp không tạo thêm container/file.

### 5.4. Reload OpenPencil hoặc mất kết nối

1. Đánh dấu editor recovering, ngừng gửi mutation mới và vô hiệu hóa runtime mapping cũ.
2. Editor đăng ký lại với workspace, token và generation hợp lệ.
3. Tìm bản đã lưu cùng các thay đổi cục bộ chưa đồng bộ. Chỉ áp dụng thay đổi cục bộ nếu đúng document và base revision; có xung đột phải giữ bản phục hồi riêng.
4. Mở đúng file, xác minh checksum/identity và cập nhật `runtime_document_id` mới.
5. Xác minh lại page/root mapping; chỉ báo ready sau khi hoàn tất.
6. Với lệnh mất kết nối giữa chừng, kiểm tra operation journal và hiện trạng trước khi thử lại; không gửi lại mutation một cách mù quáng.

### 5.5. Backend hoặc container khởi động lại

- Job và checkpoint tồn tại trong DB; startup tìm job hết heartbeat và đưa về trạng thái cần đối soát.
- Run đang chờ người dùng review tiếp tục chờ, không tự phê duyệt.
- Nếu instance còn đúng owner và còn khỏe, dùng tiếp. Nếu phải thay instance, thu hồi writer cũ rồi hydrate file vào instance mới.
- Tiếp tục từ thao tác chưa hoàn thành, không chỉ từ tên stage chung. Page đã lưu không được tạo lặp.

### 5.6. Idle, nhiều tab và xóa session

- Idle: chỉ trả instance khi không có job ghi và các thay đổi đã được lưu bền vững.
- Nhiều tab cùng session: một tab có quyền editor; tab còn lại xem trạng thái hoặc yêu cầu chuyển quyền có kiểm soát. Không để đăng ký WebSocket mới tự chiếm quyền.
- Xóa session: khóa nhận job mới, hủy/đối soát job đang chạy, thu hồi quyền editor và release instance trước khi dọn metadata.
- File và bản backup xử lý theo retention đã định. Nội dung xác nhận xóa phải nói rõ có xóa tài liệu hay chỉ phiên chat; không âm thầm xóa cả hai.

### 5.7. Nạp và sử dụng file design system

#### Cách hệ thống đang đọc thư viện

`ComponentSource.discover()` hiện đọc file `.fig` trên filesystem của backend/worker bằng OpenPencil CLI. `pack()` xuất JSX của component được chọn và lần theo các dependency; executor render gói này vào trang `Components` của tài liệu thiết kế. Cache JSX hiện dùng fingerprint SHA-256 của file nguồn.

Vì vậy cần phân biệt ba nơi: storage giữ thư viện gốc, backend/worker đọc và xuất component, OpenPencil instance nhận component để dựng file output. Mount file nguồn vào container OpenPencil thôi chưa đủ nếu backend CLI không đọc được file. Cũng không cần tự động mở toàn bộ thư viện lớn thành một tab editor cho mỗi session.

Hiện profile có một `source_file`; giai đoạn đầu giữ một design system chính cho mỗi workspace. Danh sách `library_ids` hoặc knowledge preset không đồng nghĩa code đã hỗ trợ ghép nhiều file `.fig`. Nếu cần nhiều thư viện, phải bổ sung binding theo từng library và xử lý trùng component/token rõ ràng.

#### Catalog và phiên bản thư viện

- Có catalog gồm `library_id`, tên hiển thị, phạm vi tenant/shared, `version`, `storage_key`, SHA-256, kích thước, phiên bản index/knowledge và trạng thái processing/ready/failed/archived.
- Đưa file hiện có vào catalog bằng script import quản trị. UI upload thư viện riêng có thể làm sau, dùng cùng pipeline kiểm tra và lập index.
- File mỗi version là bất biến. Upload bản mới tạo version mới; session đang chạy tiếp tục dùng bản đã chốt.
- Workspace lưu binding thư viện; mỗi run/checkpoint lưu snapshot binding để retry dùng lại đúng nguồn. Knowledge index phải khớp checksum thư viện, tránh lấy node ID từ bản khác.
- Giữ version cũ còn được workspace tham chiếu. Archive thư viện ngăn chọn mới nhưng không tự làm mất khả năng phục hồi session cũ.

Frontend lấy danh sách được phép dùng từ catalog, hiển thị tên và phiên bản, rồi gửi `library_id + version`. Backend xác minh quyền và resolve đường dẫn nội bộ. Bỏ nhập Windows path hoặc dò tên gần giống trong chế độ production; `_source()` hiện có fallback substring có thể chọn sai khi nhiều thư viện có tên tương tự.

#### Luồng từ chọn thư viện đến render

1. Khi chọn design system, backend lưu lựa chọn vào workspace. Có thể dùng mặc định của tenant nhưng phải hiển thị cho người dùng biết thư viện nào đã được chọn.
2. Worker tải đúng version từ storage vào cache hoặc đọc từ volume thư viện read-only; kiểm tra checksum trước khi dùng. Ví dụ cache nguồn nằm tại `/app/designer-data/design-systems/{library_id}/{version}/{sha256}.fig`.
3. Kiểm tra CLI có trong image worker và đọc được file. Lập index component, variant, text slot, token và dependency; báo trạng thái processing nếu chưa sẵn sàng. Không để tác vụ lập index lớn chiếm request web đồng bộ.
4. Từ yêu cầu screen, lấy các candidate liên quan trong index, rồi xuất component được chọn cùng dependency theo thứ tự phụ thuộc. LLM nhận mô tả/token/preview cần thiết cho công việc, không nhận toàn bộ file hay toàn bộ cây thư viện.
5. Render gói component vào đúng document output và lưu mapping từ `(library_id, version, source_component_id)` sang node ID đã import. Instance trong screen chỉ tham chiếu node thuộc tài liệu đích.
6. Ghi manifest của gói đã import cùng document revision: checksum nguồn, phiên bản exporter, component mapping, token mapping và asset/font cần thiết. Xác minh import đủ dependency và save trước khi coi bước Components hoàn tất.
7. Khi sửa/refine, dùng lại các component đã import và cùng phiên bản thư viện. Chỉ import thêm phần còn thiếu, tránh tạo một trang `Components` mới sau mỗi retry.

Khả năng giữ variant, variable binding, nested instance và asset qua export JSX/import phải được kiểm chứng bằng file design system đang dùng. Phần nào pipeline chưa giữ được cần báo cụ thể; không coi xuất được JSX là đã bảo toàn toàn bộ thư viện.

#### Phân phối file khi có nhiều container

| Tài nguyên | Nơi sử dụng | Cách cấp phát |
| --- | --- | --- |
| File `.fig` design system gốc | Backend/worker chạy CLI | Cache theo checksum hoặc mount read-only; storage giữ bản chuẩn |
| Index, knowledge và JSX đã xuất | Worker lập kế hoạch/đóng gói | Cache riêng theo checksum nguồn và phiên bản công cụ/index |
| Component/token đã import | Document trong OpenPencil instance | Lưu trong file output cùng manifest; kiểm chứng bằng save/reopen |
| Font và ảnh liên quan | Editor runtime và bộ render | Cấp qua tài nguyên được phép truy cập, chờ tải xong trước đo layout/chụp ảnh |

Cache được chia sẻ chỉ trong phạm vi quyền cho phép. Dùng khóa theo cache key và ghi atomic để hai worker không đọc gói đang xuất dở. Cache key phải tính cả phiên bản CLI/exporter; chỉ hash file nguồn chưa đủ khi định dạng JSX hoặc cách export thay đổi. Cache là dữ liệu có thể dựng lại, không thay thế bản thư viện gốc.

Nếu tool cụ thể cần đọc trực tiếp file nguồn trong OpenPencil container, allocator phải cấp cùng checksum tại đường dẫn nằm trong MCP root được cho phép. Backend source path và MCP path là hai đường dẫn riêng được resolve từ cùng library version; không giả định chúng giống nhau giữa host và container.

#### Mở lại session, đổi thư viện và xử lý lỗi

- Khi restore, đọc manifest và xác minh component mapping trong `.fig` đã lưu. Mapping thiếu hoặc node ID thay đổi cần đối soát trước khi import lại; không dùng source node ID làm runtime ID.
- Nếu tài liệu đã chứa đủ component/assets, mở xem tài liệu không cần tải và export lại toàn bộ design system. Công việc cần tra cứu hoặc thêm component phải resolve đúng version đã chốt.
- Khi cache trống hoặc đổi worker, tải lại đúng version từ storage. Nếu nguồn đang lỗi, giữ file thiết kế hiện tại và cho retry phần nạp thư viện; không tạo lại dự án hoặc tự thay thư viện khác.
- Đổi design system trên workspace đã thiết kế là thao tác có phạm vi: áp dụng cho screen mới hay migrate cả screen cũ. Lưu revision trước khi migrate, cập nhật binding và manifest sau khi hoàn tất; không đổi giữa một job đang ghi.
- Trạng thái UI tối thiểu: tên/phiên bản thư viện, đang chuẩn bị, sẵn sàng hoặc chưa tải được. Thông báo lỗi chỉ rõ file nguồn, index, dependency hay font gặp vấn đề, kèm cách thử lại phù hợp.

Fonts là điều kiện của kiểm thử layout: phải xác minh font tiếng Việt và weight thực sự được renderer tải. Nếu dùng fallback, kết quả đo chữ và refine có thể khác thiết kế dự kiến; ghi nhận font thực tế trong bằng chứng kiểm tra.

## 6. Lưu file và checkpoint nhất quán

Mỗi revision được lưu vào key riêng, ví dụ:

```text
tenants/{tenant_id}/workspaces/{workspace_id}/documents/{document_id}/revisions/{revision}.fig
```

Thứ tự commit:

1. Ghi operation journal: operation ID, base revision, screen/page đích và trạng thái đang thực hiện.
2. Sau mutation, xuất `.fig`, ghi bản làm việc bằng temporary file rồi atomic rename trên cùng filesystem.
3. Upload revision mới, xác minh checksum và lưu các bằng chứng kiểm tra liên quan.
4. Transaction DB cập nhật revision hiện tại, checkpoint và trạng thái operation; chỉ thành công nếu base revision và writer epoch còn đúng.
5. Phát event “đã lưu” sau commit. Nếu event bị mất, bootstrap/event replay vẫn phản ánh dữ liệu đã commit.

Object storage và DB không có transaction chung. Upload thành công nhưng DB thất bại có thể để lại object chưa được tham chiếu; giữ object để đối soát và dọn sau. Không cập nhật checkpoint thành công trước khi file tương ứng được lưu.

Autosave phải bao phủ thao tác trực tiếp trong editor. IndexedDB giữ thay đổi cục bộ để phục hồi trên cùng trình duyệt; storage server giữ bản dùng khi đổi máy hoặc thay container. Debounce vẫn có khoảng thời gian chưa lưu, vì vậy không cam kết mất điện/đóng máy đột ngột sẽ giữ mọi thao tác chưa được xác nhận. Không dựa vào `beforeunload` làm cơ chế lưu chính.

## 7. Kế hoạch phát triển theo giai đoạn

### Giai đoạn 0 — Chốt baseline và ca tái hiện

- Ghi lại commit, diff hiện tại và các container/config đang sử dụng; backup DB, file `.fig` và đầu vào BA.
- Dựng môi trường kiểm thử tách khỏi file đang demo.
- Tái hiện reload frontend, reload OpenPencil, tab ID trùng, hai run cùng session và restart backend.
- Ghi trace với session/run/workspace/document để đối chiếu trước và sau thay đổi.
- Kiểm kê file design system, checksum, knowledge index, font và dependency đang dùng; thử CLI export/import/save/reopen trên thư viện thực tế.

Hoàn thành khi mỗi lỗi định tuyến/phục hồi có ca tái hiện và dữ liệu thử riêng.

### Giai đoạn 1 — Định danh và routing theo session

- Migration workspace/document ID bền vững, runtime mapping và screen registry theo platform.
- Bootstrap API, URL session và xử lý response/event cũ ở frontend.
- Endpoint do backend cấu hình; pool có thể là danh sách instance cố định ở bước này.
- Kiểm tra identity trước mọi tool call; loại bỏ fallback sang active tab hoặc tạo file mới khi recovery mismatch.
- Chuyển dữ liệu cũ theo session và file path đã xác minh, không theo `tab-N`. Binding chưa xác minh chuyển trạng thái cần phục hồi.
- Tạo catalog design system và binding version theo workspace/run; chuyển selector từ path cục bộ sang library ID/version. Migration chỉ gán bản nguồn đã xác minh, không đoán version của run cũ khi file nguồn đã thay đổi.

Hoàn thành khi reload/chuyển session luôn về đúng workspace, và hai workspace không thể nhận chung một instance active.

### Giai đoạn 2 — Lưu bền vững và phục hồi editor

- Storage revision, checksum, operation journal và commit checkpoint như mục 6.
- Gắn document identity và cơ chế autosave cho tài liệu do agent tạo.
- Restore handshake, runtime generation và quy tắc một editor writer.
- Lưu/khôi phục page đang xem, đồng thời xác minh node IDs sau import.
- Dùng hạ tầng IndexedDB/outbox sẵn có của OpenPencil nếu phù hợp; tránh tạo thêm hai cơ chế autosave cạnh tranh.
- Lưu manifest component/token, kiểm thử reopen giữ đủ dependency và font/asset; cache export theo checksum và phiên bản công cụ, retry import không tạo component trùng.

Hoàn thành khi reload editor mở đúng revision, thao tác chưa đồng bộ có đường phục hồi, và mất kết nối không tạo page lặp.

### Giai đoạn 3 — Worker và nhiều container

- PostgreSQL, durable jobs, heartbeat, lease và cơ chế chặn writer cũ.
- Worker claim job theo workspace; cancel/retry qua DB để có hiệu lực giữa các process.
- Instance registry và allocator có thể bắt đầu với pool cố định, sau đó thêm tạo/hủy container theo nhu cầu.
- Readiness kiểm tra MCP + bridge + restored document, tách khỏi liveness của process.
- Idle release, quota concurrency, giới hạn CPU/RAM và thời gian provisioning.
- Cấp design system đúng đường dẫn worker/container, tải lại khi cache trống và kiểm tra quyền thư viện khi phân bổ instance; đo chi phí cold start với thư viện lớn.
- Kiểm thử pause/resume khi browser đóng; nếu cần chạy không có browser người dùng, hoàn thành thêm browser worker và cơ chế xem/sửa cùng runtime trước khi phát hành tính năng đó.

Hoàn thành khi restart backend hoặc thay container vẫn tiếp tục được đúng checkpoint, và worker cũ bị từ chối ghi sau khi mất quyền.

### Giai đoạn 4 — Triển khai pilot rồi production

- Xác thực người dùng; kiểm tra quyền sở hữu tại session, run, artifact, preview, attachment và route OpenPencil.
- Chạy web qua HTTPS; MCP chỉ ở mạng nội bộ. Không nhận endpoint/path tùy ý từ client và không chuyển token MCP dùng chung đến URL do client cung cấp.
- Token riêng cho instance, quyền storage giới hạn theo workspace; component library mount read-only.
- Backup DB/storage và kiểm thử restore thực tế, không chỉ kiểm tra backup job thành công.
- Backup cả thư viện gốc theo version và catalog/manifest; thử restore khi cache component đã bị xóa và khi thư viện có version mới hơn.
- Pilot với ít workspace đồng thời, theo dõi tài nguyên và lỗi trước khi tăng pool.

Hoàn thành khi bộ kiểm thử ở mục 8 đạt trên môi trường staging giống production, có số liệu tải và diễn tập phục hồi.

## 8. Tiêu chí nghiệm thu

| Tình huống | Kết quả bắt buộc |
| --- | --- |
| Reload frontend khi đang thiết kế | Giữ đúng session URL, workflow và tài liệu; không gửi lại request tạo run |
| Chuyển A → B khi request A còn chậm | Response/event A không ghi đè UI hoặc picker B |
| Reload OpenPencil | Restore đúng document/revision; cập nhật tab ID; chỉ tiếp tục khi ready |
| `tab-2` mới thuộc file khác | Phát hiện identity mismatch trước mọi mutation |
| Hai session hoạt động đồng thời | Mỗi session có instance riêng; file và ảnh refine không lẫn nhau |
| Hai tab gửi lệnh cùng workspace | Chỉ một writer; lệnh còn lại được xếp hàng hoặc báo đang bận |
| Lệnh render đã chạy nhưng mất response | Đối soát trước retry; không tạo thêm page/root trùng |
| Worker mất lease rồi nhận lại response cũ | Không commit revision/checkpoint và không gửi mutation tiếp |
| Backend restart giữa workflow | Khôi phục job/checkpoint; không treo trạng thái running vô hạn |
| Container bị thay | Mở file đã commit từ storage và tiếp tục đúng screen |
| Upload thành công, DB commit thất bại | Không báo đã lưu; đối soát được revision chưa tham chiếu |
| Người dùng sửa tay rồi reload | Phục hồi bản đã lưu; bản cục bộ chưa sync được giữ hoặc báo xung đột |
| Screen có desktop và mobile | Registry giữ đủ cả hai mapping sau reload |
| Refine screen dài | Bằng chứng ảnh phủ toàn screen, đọc được vùng chi tiết và khớp revision |
| Worker mới chưa có design system | Tải đúng version/checksum, CLI đọc được source và import thành công vào đúng output |
| Hai thư viện trùng tên hoặc source node ID | Resolve bằng library ID/version; không dò substring hoặc trộn component mapping |
| Thư viện được cập nhật trong lúc chạy | Run/retry vẫn dùng version đã chốt; không đổi component/token âm thầm |
| Cache export dở hoặc công cụ export đổi version | Không dùng cache chưa hoàn tất hoặc không tương thích; dựng lại từ nguồn đã xác minh |
| Mất thư viện/cache khi mở lại file output | File đã lưu vẫn xem được nếu có đủ tài nguyên; tác vụ cần nguồn báo đúng trạng thái và retry riêng |
| Nested component, token, ảnh và font tiếng Việt | Save/reopen giữ dependency cần thiết; hình và số đo chữ khớp renderer thực tế |
| Retry sau import component nhưng trước checkpoint | Đối soát manifest/node mapping; không tạo thêm bản component trùng |
| Tenant không có quyền với design system | Catalog, nguồn file và cache/export đều từ chối truy cập |
| User khác đoán được session/preview URL | API và gateway từ chối truy cập |
| Xóa session đang chạy | Worker/editor mất quyền ghi; instance không còn giữ binding của session |
| Khôi phục từ backup | Đọc được file, metadata và workflow tương ứng trên môi trường mới |

Không dùng một lần chạy demo thành công làm bằng chứng ổn định. Bộ nghiệm thu phải có fault injection tại ranh giới render, save, upload, commit và reconnect.

## 9. Vận hành, rollout và rollback

Log theo `tenant_id`, `session_id`, `workspace_id`, `run_id`, `operation_id`, `instance_id`, runtime generation và document revision. Không ghi token hoặc toàn bộ tài liệu BA vào log vận hành.

Theo dõi tối thiểu: độ trễ cấp instance, thời gian restore, số lần bridge disconnect, lỗi save, job mất heartbeat, độ dài hàng đợi và CPU/RAM theo instance. Với design system, đo thời gian tải/lập index/export/import, cache hit và lỗi checksum/dependency/font; log library ID/version đi cùng run. Cảnh báo khi save liên tục thất bại hoặc job không còn tiến triển; retry có giới hạn và backoff.

Triển khai bằng migration bổ sung tương thích dữ liệu cũ và feature flag cho routing mới. Bắt đầu với session mới ở staging/pilot. Với session cũ, chỉ kích hoạt sau khi tìm và xác minh được file gốc; giữ nguyên bản gốc trong quá trình migration.

Trước khi nâng cấp worker/container, ngừng cấp job mới cho instance sắp dừng, chờ save hoặc chuyển job về trạng thái phục hồi, rồi mới thay runtime. Khi rollback, không đưa workspace đã migrate về cơ chế chọn `tab-N` cũ. Có thể tạm dừng ghi, giữ quyền xem/tải bản đã commit và chạy lại phiên bản tương thích schema/storage mới.

Chưa đặt số container, mức RAM hay SLA bằng phỏng đoán. Đo trên bộ screen mobile/desktop thực tế của Aurora, gồm cả tài liệu nhiều page và refine ảnh dài; từ đó chọn giới hạn concurrency, idle timeout và mục tiêu thời gian phục hồi.

## 10. Phạm vi bàn giao

Kết quả của kế hoạch gồm migration, API/bootstrap, frontend routing, OpenPencil restore/identity, lưu revision, catalog và pipeline nạp design system, worker/pool, cấu hình triển khai và báo cáo nghiệm thu. Giữ workflow thiết kế và prompt nghiệp vụ hiện có; những thay đổi trong kế hoạch này tập trung vào quyền sở hữu, lưu trữ và thực thi để thiết kế chạy trên đúng tài liệu và đúng phiên bản thư viện.

Mốc mở production là khi hệ thống chứng minh được: một workspace chỉ có một writer hợp lệ; file đã báo lưu phục hồi được; reload/restart tiếp tục đúng tiến độ; request của người dùng này không thể đọc hoặc sửa workspace của người dùng khác. Chất lượng thẩm mỹ vẫn phải được đánh giá riêng trên thiết kế và bằng chứng refine, không suy ra từ việc hạ tầng hoạt động ổn định.

## 11. Chiến lược đóng gói để giữ behavior của OpenPencil

### Vấn đề hiện tại

Dockerfile ở source OpenPencil chạy `build:packages` rồi `vite build` từ chính working tree. Vì vậy các thay đổi trong `src/`, `packages/mcp/`, `vite.config.ts` và các package workspace đều được compile vào image. `compose.yaml` hiện dùng tag mutable `openpencil:local`; cùng một tag có thể trỏ tới nhiều nội dung khác nhau sau các lần build.

Working tree hiện cũng có nhiều file sửa chưa commit. Nếu đóng gói trực tiếp từ thư mục này, image sẽ đúng với máy build nhưng khó biết khác upstream ở đâu và khó rollback.

### Cấu trúc source cần chốt

Giữ một fork có upstream/tag rõ ràng:

```text
upstream open-pencil tag/commit
        |
        +-- patch: MCP target routing và auth
        +-- patch: session/storage restore
        +-- patch: save/autosave integration
        +-- patch: export/refine page identity
```

Mỗi patch phải có mục đích hẹp, test đi kèm và ghi rõ có thay đổi behavior mặc định hay không. Không dùng việc format toàn bộ repository như một patch chức năng; diff format lớn làm khó review và merge upstream. Gắn upstream commit vào build metadata, ví dụ `OPENPENCIL_UPSTREAM_SHA`, `OPENPENCIL_PATCHSET_SHA` và phiên bản application.

### Hai profile build

Image nên có hai profile chính:

1. **Compatibility profile**: giữ các giá trị mặc định, menu, thao tác file và hành vi editor của OpenPencil gốc. Phần Designer integration chỉ được bật khi có request MCP hợp lệ hoặc biến cấu hình rõ ràng.
2. **Designer runtime profile**: bật browser automation, session routing, persistent storage và các tool MCP cần Designer Agent.

Không làm hai profile bằng cách copy hai bộ source khác nhau. Dùng cùng một commit, cùng lockfile và cùng artifact build, chỉ khác feature flag/runtime config khi thay đổi đó an toàn ở runtime. Những thay đổi ảnh hưởng schema, RPC protocol hoặc target resolution phải được kiểm tra ở cả hai profile.

Feature flag cần có default tương thích với OpenPencil gốc trong môi trường dùng độc lập. Production Designer đặt flag từ image manifest hoặc deployment config; frontend không tự bật flag bằng localStorage.

### Build reproducible

- Build từ một commit đã được tag, không build từ thư mục đang có thay đổi chưa commit.
- Dùng `bun.lock` đã commit và `bun install --frozen-lockfile` như Dockerfile hiện tại.
- Ghi SHA, package versions, Node/Bun version và danh sách flag vào `/app/build-info.json` hoặc image label.
- Đặt image tag bất biến theo git SHA, ví dụ `openpencil:<designer-agent-sha>-<upstream-sha>`, rồi deploy digest; không dùng `openpencil:local` ở production.
- Tách build stage và runtime stage; runtime chỉ chứa `dist`, package runtime, MCP package đã build và entrypoint. Không copy source development hoặc secret vào image runtime.
- `.fig`, design system, database và cache không nằm trong image. Chúng phải ở volume/object storage bên ngoài để đổi image không mất dữ liệu.
- Dùng registry có provenance/signature và giữ image cũ đủ lâu để rollback.

### Kiểm tra behavior gốc trước khi phát hành

CI phải chạy theo ba lớp:

- Unit/type/lint cho các package bị sửa.
- OpenPencil regression smoke test: mở file, tạo tab, đổi page, save/open, export, undo/redo, reload, MCP health và browser reconnect.
- Designer integration test: claim đúng instance, target đúng document/page, save revision, restart container rồi restore, hai workspace không dùng chung runtime.

Giữ một bộ fixture `.fig` nhỏ và snapshot JSON/ảnh cho behavior quan trọng. So sánh với image built từ upstream commit trong cùng pipeline. Một thay đổi chỉ được coi là tương thích khi chênh lệch là do test case đã được chấp nhận; không dùng screenshot pass/fail duy nhất để thay cho kiểm tra file và target.

Smoke test tối thiểu sau khi image chạy:

```text
GET /health                         -> process đang sống
GET /health với bridge đã đăng ký   -> app bridge sẵn sàng
list_documents                      -> trả document metadata hợp lệ
new_document + save_file            -> tạo file trong storage root
open_file sau restart               -> mở đúng checksum/revision
list_pages(document_id)             -> page thuộc đúng document
render/export page                  -> target page đúng, không dùng active tab ngầm
```

Healthcheck của Docker phải kiểm tra readiness của MCP và browser bridge khi profile Designer yêu cầu. Process web trả HTTP 200 riêng không chứng minh instance có thể nhận lệnh thiết kế.

### Cách tổ chức release

1. Rebase hoặc merge fork với upstream trong nhánh riêng.
2. Chạy test compatibility và Designer integration.
3. Tạo image candidate bất biến, kiểm tra manifest và smoke test trong container mới.
4. Deploy staging bằng chính image digest production dự kiến.
5. Chạy migration/storage restore và fault injection: restart MCP, restart web, mất bridge, mất response sau save.
6. Deploy canary với số workspace nhỏ; quan sát restore, save, instance lease và lỗi MCP.
7. Mở rộng dần; giữ image digest trước đó và schema migration tương thích để rollback.

Rollback chỉ thay image/runtime, không xóa volume hoặc object storage. Nếu patch đã thay đổi định dạng metadata, phải có migration ngược hoặc giữ worker cũ đọc được revision cũ. Không dùng `docker compose build` trên production như quy trình phát hành; build ngoài CI, scan và publish image trước.

### Quy tắc khi cập nhật OpenPencil upstream

- Ghi nhận upstream commit và đọc release notes trước khi merge.
- Chạy patch apply/compile ở CI, không sửa trực tiếp trong image.
- Kiểm tra các vùng dễ xung đột: tab identity, browser bridge, MCP tool schemas, save targets, storage adapters và Vite build flags.
- Nếu upstream thay đổi protocol hoặc graph serialization, tăng `runtime_generation`/compatibility version và kiểm tra file `.fig` cũ trước khi cho worker mới ghi.
- Chỉ bỏ patch khi đã có behavior tương đương được test; không xóa vì patch “không còn cần” mà chưa kiểm tra recovery và multi-instance.
