# Solution Lesson — Day 13 Observability Lab

Tài liệu này giải thích **3 TODO đã hoàn thành** (`app/middleware.py`, `app/pii.py`,
`app/logging_config.py`, `app/main.py`) — cái gì, vì sao, và cách trả lời khi
giảng viên hỏi xoáy trong phần demo.

---

## 0. Luồng tổng quan của 1 request `/chat`

```
Client ──▶ CorrelationIdMiddleware ──▶ /chat endpoint ──▶ LabAgent.run() ──▶ Response
              │                            │                    │
              │ 1. clear_contextvars()     │ 3. bind_contextvars │ 4. @observe() trace
              │ 2. bind correlation_id     │    (user/session/   │    + metrics.record_request
              │                            │     feature/model)  │
              ▼                            ▼                     ▼
        mọi log.info() phía sau TỰ ĐỘNG có các field này gắn kèm
        → đi qua pipeline structlog (scrub PII) → ghi data/logs.jsonl
```

**Ý chính**: `contextvars` là "túi đựng" theo từng request (an toàn với
`async`/concurrent). Middleware mở túi và bỏ `correlation_id` vào; endpoint bỏ
thêm `user_id_hash`, `session_id`, `feature`, `model`, `env`. Mọi `log.info(...)`
từ thời điểm đó đến cuối request tự động "moi" các giá trị trong túi ra và gắn
vào JSON log — **không cần truyền tay từng lệnh log**.

---

## 1. Correlation ID Middleware — `app/middleware.py`

```python
class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        clear_contextvars()

        correlation_id = request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:8]}"

        bind_contextvars(correlation_id=correlation_id)
        request.state.correlation_id = correlation_id

        start = time.perf_counter()
        response = await call_next(request)

        response.headers["x-request-id"] = correlation_id
        response.headers["x-response-time-ms"] = str(int((time.perf_counter() - start) * 1000))
        return response
```

| Dòng | Vì sao |
|---|---|
| `clear_contextvars()` **đầu tiên** | Nếu không clear, context của request trước (chạy trên cùng worker/thread) có thể "leak" sang request hiện tại → 2 request khác nhau bị gắn cùng 1 `correlation_id`. |
| `request.headers.get("x-request-id") or f"req-{uuid4().hex[:8]}"` | Cho phép **client tự đặt ID** (hữu ích khi 1 request đi qua nhiều service — giữ nguyên 1 ID xuyên suốt hệ thống). Nếu client không gửi, server tự sinh theo format `req-<8 hex>`. |
| `bind_contextvars(correlation_id=...)` | Gắn ID vào context — **không sửa đổi từng dòng log** trong toàn bộ codebase, chỉ cần bind 1 lần. |
| `request.state.correlation_id` | Lưu thêm vào `request.state` để endpoint có thể trả về trong `ChatResponse.correlation_id` (response body, khác với response header). |
| `response.headers["x-request-id"]` / `x-response-time-ms` | Trả ID + thời gian xử lý ra **HTTP header** — client/Postman/giám sát có thể đọc mà không cần parse body. |

**Câu hỏi demo thường gặp**: *"Tại sao `clear_contextvars()` phải đứng trước cả
khi sinh `correlation_id`?"* → Vì nó dọn sạch context cũ trước khi context mới
được set, tránh race condition giữa các request chạy đan xen.

---

## 2. PII Scrubbing — `app/pii.py`

```python
PII_PATTERNS: dict[str, str] = {
    "email": r"[\w\.-]+@[\w\.-]+\.\w+",
    "phone_vn": r"(?:\+84|0)[ \.-]?\d{3}[ \.-]?\d{3}[ \.-]?\d{3,4}",
    "cccd": r"\b\d{12}\b",
    "credit_card": r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",
    "passport_vn": r"\b[A-Z]\d{7,8}\b",          # mới thêm
    "address_vn": r"\b\d{1,4}(?:/\d+)?\s+(?:[Đđ]ường|[Pp]hố|[Nn]gõ|[Hh]ẻm)\s+[^\n,]{2,50}",  # mới thêm
}
```

- **`passport_vn`**: hộ chiếu Việt Nam có format `1 chữ in hoa + 7-8 số` (ví dụ
  `B1234567`). Regex `\b[A-Z]\d{7,8}\b` bắt đúng pattern này.
- **`address_vn`**: bắt cụm "số nhà + đường/phố/ngõ/hẻm + tên đường" (ví dụ
  `123 Đường Nguyễn Huệ`). Regex dừng tại dấu phẩy hoặc xuống dòng để không "ăn"
  luôn cả câu phía sau.
- **Trade-off quan trọng**: regex PII luôn phải cân bằng giữa
  - *false negative* (PII thật bị bỏ sót → rò rỉ dữ liệu — nguy hiểm hơn), và
  - *false positive* (redact nhầm text không phải PII → mất thông tin hữu ích cho debug).

  Đây là lý do `\b` (word boundary) và giới hạn độ dài `{2,50}` được dùng — để
  regex không "ăn" lan ra toàn câu.

- **`scrub_text()`**: chạy tuần tự từng pattern, thay bằng `[REDACTED_<TÊN>]`.
  Vì chạy tuần tự trên text đã bị redact ở bước trước, **thứ tự dict không gây
  xung đột** ở đây vì các pattern target format khác nhau (email có `@`, số
  điện thoại/CCCD/thẻ là số, passport có 1 chữ cái đầu, địa chỉ có từ khóa
  tiếng Việt).

- **`hash_user_id()`**: khác với `scrub_text` (redact/che), đây là **one-way
  hash** (SHA-256, lấy 12 ký tự đầu) — dùng khi vẫn cần **phân biệt được user
  này với user khác** trong log/trace (để debug "user X bị lỗi nhiều lần") mà
  không lưu `user_id` thật → đây chính là field `user_id_hash`.

**Câu hỏi demo thường gặp**: *"Vì sao không hash luôn cả email/SĐT thay vì
redact?"* → Vì hash vẫn giữ tính **định danh duy nhất** (2 email khác nhau ra 2
hash khác nhau) — phù hợp cho `user_id` cần truy vết, nhưng **không phù hợp**
cho nội dung tự do (message) vì không cần biết "ai" đã gõ email đó, chỉ cần
không để lộ nó.

---

## 3. Structured Logging Pipeline — `app/logging_config.py`

```python
structlog.configure(
    processors=[
        merge_contextvars,                              # 1. lấy correlation_id, user_id_hash,... từ contextvars
        structlog.processors.add_log_level,             # 2. thêm field "level"
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),  # 3. thêm "ts"
        scrub_event,                                     # 4. redact PII  ⬅ MỚI BẬT
        structlog.processors.StackInfoRenderer(),       # 5. thêm stack trace nếu có
        structlog.processors.format_exc_info,           # 6. format exception
        JsonlFileProcessor(),                            # 7. ghi ra data/logs.jsonl
        structlog.processors.JSONRenderer(),             # 8. render JSON ra console
    ],
    ...
)
```

structlog xử lý mỗi log statement qua một **chain processor theo đúng thứ tự
khai báo** — mỗi processor nhận `event_dict` (dict), có thể sửa rồi trả về cho
processor kế tiếp.

**Vì sao `scrub_event` phải đặt ở bước 4 (trước `JsonlFileProcessor`)?**
- `JsonlFileProcessor` (bước 7) là nơi **ghi file thật** — nếu `scrub_event`
  đặt sau bước 7, dữ liệu PII đã bị ghi ra `data/logs.jsonl` rồi, scrub lúc đó
  vô nghĩa.
- `scrub_event` cũng phải đặt **sau** `merge_contextvars`/`TimeStamper` — không
  bắt buộc về thứ tự với 2 processor này, nhưng đặt sau để đảm bảo nó scrub
  trên `event_dict` đã đầy đủ field (kể cả các field được merge từ contextvars,
  ví dụ nếu lỡ có PII trong `session_id`).

**`scrub_event()` hoạt động trên 2 chỗ**:
```python
def scrub_event(_, __, event_dict):
    payload = event_dict.get("payload")
    if isinstance(payload, dict):
        event_dict["payload"] = {k: scrub_text(v) if isinstance(v, str) else v for k, v in payload.items()}
    if "event" in event_dict and isinstance(event_dict["event"], str):
        event_dict["event"] = scrub_text(event_dict["event"])
    return event_dict
```
- `payload` dict (nơi `message_preview`, `answer_preview` được đặt) → scrub
  từng giá trị string.
- `event` (tên log event, ví dụ `"request_received"`) → scrub luôn (đề phòng
  ai vô tình nhúng PII vào message tên event).

**Câu hỏi demo thường gặp**: *"Nếu đổi vị trí `scrub_event` xuống sau
`JsonlFileProcessor` thì điều gì xảy ra?"* → File log sẽ chứa PII chưa redact
(`validate_logs.py` sẽ FAIL mục "PII scrubbing", trừ 30 điểm), vì console output
(qua `JSONRenderer` ở bước 8) vẫn được scrub nhưng file đã ghi ra trước đó rồi.

---

## 4. Log Enrichment — `app/main.py`

```python
@app.post("/chat", response_model=ChatResponse)
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    bind_contextvars(
        user_id_hash=hash_user_id(body.user_id),
        session_id=body.session_id,
        feature=body.feature,
        model=agent.model,
        env=os.getenv("APP_ENV", "dev"),
    )

    log.info("request_received", service="api", payload={...})
    ...
```

- `bind_contextvars(...)` chạy **1 lần** ở đầu endpoint. Từ đó, **mọi**
  `log.info`/`log.error` trong cùng request (`request_received`,
  `response_sent`, `request_failed`) tự động có 5 field này — đúng với
  `ENRICHMENT_FIELDS` mà `scripts/validate_logs.py` kiểm tra
  (`user_id_hash`, `session_id`, `feature`, `model`) cộng thêm `env` theo
  `config/logging_schema.json`.
- `hash_user_id(body.user_id)`: không log `user_id` thô (vd `"u01"` — trong lab
  này không nhạy cảm, nhưng trong thực tế `user_id` thường là email/số điện
  thoại/ID nội bộ) → log `user_id_hash` để vẫn lọc/group theo user mà không lộ
  danh tính.
- `agent.model`: lấy từ `LabAgent.model` (hard-code `"claude-sonnet-4-5"`
  trong `agent.py`) — nếu sau này hỗ trợ multi-model, field này cho biết
  request nào dùng model nào (quan trọng để debug chất lượng/cost theo model).
- `os.getenv("APP_ENV", "dev")`: phân biệt log từ môi trường `dev`/`staging`/
  `prod` — cùng 1 dashboard có thể filter theo `env`.

**Vì sao dùng `bind_contextvars` thay vì truyền `user_id_hash=..., session_id=...`
vào từng `log.info()`?**
→ DRY (Don't Repeat Yourself): endpoint `/chat` có 3 chỗ log (`request_received`,
`response_sent`, `request_failed` trong `except`). Nếu truyền tay, dễ quên 1
chỗ → field bị thiếu → `validate_logs.py` báo `missing_enrichment`. Bind 1 lần
ở đầu đảm bảo **tất cả** các log phía sau đều nhất quán.

---

## 5. Kết quả kiểm chứng (`scripts/validate_logs.py`)

Sau khi chạy `uvicorn app.main:app` + gửi 10 request từ
`data/sample_queries.jsonl` (gồm các câu chứa email, SĐT, thẻ tín dụng test):

```
--- Lab Verification Results ---
Total log records analyzed: 21
Records with missing required fields: 0
Records with missing enrichment (context): 0
Unique correlation IDs found: 10
Potential PII leaks detected: 0

--- Grading Scorecard (Estimates) ---
+ [PASSED] Basic JSON schema
+ [PASSED] Correlation ID propagation
+ [PASSED] Log enrichment
+ [PASSED] PII scrubbing

Estimated Score: 100/100
```

Giải thích từng dòng:
- **21 records** = 1 `app_started` + 10×(`request_received` + `response_sent`).
- **10 unique correlation IDs** = mỗi request có ID riêng (middleware hoạt động
  đúng, không bị leak giữa các request).
- **0 PII leaks**: log số 1 (`"My email is student@vinuni.edu.vn"`) và số 9
  (`"...credit card 4111 1111 1111 1111?"`) đều xuất hiện trong
  `data/logs.jsonl` dưới dạng `[REDACTED_EMAIL]` / `[REDACTED_CREDIT_CARD]`.

---

## 6. Phần đã có sẵn (không cần sửa, nhưng nên hiểu để demo)

### Tracing — `app/agent.py` + `app/tracing.py`
- `@observe()` (decorator của Langfuse) tự động tạo 1 **trace** mỗi lần
  `LabAgent.run()` chạy.
- `langfuse_context.update_current_trace(user_id=..., session_id=..., tags=[...])`
  gắn metadata cấp **trace** (toàn bộ request).
- `langfuse_context.update_current_observation(metadata=..., usage_details=...)`
  gắn metadata cấp **observation/span** (riêng phần gọi LLM).
- Nếu `.env` không có `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` → fallback thành
  no-op (dummy), `tracing_enabled() == False`. **Cần set 2 key này** để traces
  lên được Langfuse dashboard (yêu cầu ≥10 traces).

### Metrics — `app/metrics.py`
- Lưu list `REQUEST_LATENCIES`, `REQUEST_COSTS`, `QUALITY_SCORES`,... trong
  memory (mất khi restart server — chỉ phù hợp demo, không phải production).
- `percentile(values, p)`: sort danh sách rồi lấy phần tử ở vị trí
  `round(p/100 * n + 0.5) - 1` — cách tính percentile đơn giản ("nearest rank
  method"), dùng cho p50/p95/p99 hiển thị trên dashboard 6-panel
  (`docs/dashboard-spec.md`).

---

## 7. Bộ câu hỏi tự ôn (cho phần Live Demo / Q&A)

1. `contextvars` khác gì với biến global thông thường? Vì sao cần nó trong app
   `async`?
2. Nếu 2 request đến gần như đồng thời, làm sao đảm bảo log của chúng không bị
   trộn `correlation_id`?
3. Giải thích vì sao thứ tự processor trong `structlog.configure()` ảnh hưởng
   đến việc PII có bị lọt ra file log hay không.
4. Sự khác biệt giữa "redact" (`[REDACTED_EMAIL]`) và "hash"
   (`hash_user_id`) — khi nào dùng cái nào?
5. Field `correlation_id` xuất hiện ở 2 nơi: HTTP response header
   (`x-request-id`) và response body (`ChatResponse.correlation_id`). Vì sao
   cần cả 2?
6. Nếu regex `passport_vn` (`\b[A-Z]\d{7,8}\b`) vô tình match nhầm 1 mã sản
   phẩm dạng `A1234567`, đây là false positive hay false negative? Cách giảm
   thiểu?
7. `percentile()` trong `metrics.py` tính theo phương pháp nào? Nếu
   `REQUEST_LATENCIES = [100, 200, 300, 400]`, `p95` trả về giá trị gì và tại
   sao?
