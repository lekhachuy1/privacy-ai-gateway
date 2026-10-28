from contextlib import asynccontextmanager, nullcontext
from collections import defaultdict, deque
import asyncio
import base64
import re
import secrets
import time
import weakref

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ValidationError, field_validator
from starlette.middleware.sessions import SessionMiddleware

from .config import ROOT, settings
from .database import (
    audit, create_conversation, delete_conversation, get_conversation,
    get_cross_session_memory, get_user, init_db, list_conversations, purge_expired,
    save_message, statistics,
)
from .security import hash_password, verify_password
from .services.ai_router import AIRouter
from .services.image_guard import MAX_IMAGE_BYTES, ImageReport, OCRUnavailable, analyze_image, detect_ocr_text, ocr_available
from .services.masker import label_tokens, mask, restore_tokens, tokens_in
from .services.output_scanner import sanitize_output
from .services.pii_detector import detect, normalize_text
from .services.policy_engine import decide
from .services.token_vault import TokenVault


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


APP_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

app = FastAPI(title="Privacy AI Gateway Demo", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.app_secret,
    same_site="strict",
    https_only=settings.session_https_only,
    max_age=settings.session_max_age_seconds,
)
app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "app" / "templates")
router = AIRouter(settings)
token_vault = TokenVault(settings.token_vault_key, settings.app_secret)
login_attempts: dict[str, deque[float]] = defaultdict(deque)
# Băm sẵn một mật khẩu ngẫu nhiên: tài khoản không tồn tại vẫn tốn đúng một lần
# PBKDF2, nên không đoán được username có tồn tại hay không qua thời gian phản hồi.
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))
# Mỗi phiên chỉ xử lý một lượt chat tại một thời điểm, nếu không hai request song
# song có thể cấp cùng một token mới cho hai giá trị khác nhau.
_conversation_locks: "weakref.WeakValueDictionary[str, asyncio.Lock]" = weakref.WeakValueDictionary()
_PARTIAL_TOKEN = re.compile(r"\[[A-Z_]*\d*$")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    path = request.url.path
    if path.startswith("/api/"):
        # Phản hồi API chứa dữ liệu thật đã khôi phục; không để trình duyệt/proxy lưu cache.
        response.headers["Cache-Control"] = "no-store"
    if path == "/":
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        )
    return response


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=100)


class AnalyzeBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=settings.ai_max_input_chars)

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        # Bộ gõ dấu tổ hợp, chữ số full-width hay ký tự vô hình làm mẫu nhận
        # diện bỏ sót; chuẩn hóa trước để dữ liệu thật không lọt ra ngoài.
        value = normalize_text(value)
        if not value.strip():
            raise ValueError("Prompt không được để trống")
        if len(value) > settings.ai_max_input_chars:
            raise ValueError(f"Prompt dài quá {settings.ai_max_input_chars} ký tự")
        return value


class ChatBody(AnalyzeBody):
    conversation_id: str | None = Field(default=None, max_length=64)
    remember: bool = True
    use_cross_session_memory: bool = True


def current_user(request: Request) -> dict:
    user_id = request.session.get("user_id")
    username = request.session.get("username")
    if not user_id or not username:
        raise HTTPException(401, "Bạn chưa đăng nhập")
    return {"id": user_id, "username": username}


def require_csrf(request: Request) -> None:
    expected = request.session.get("csrf_token")
    supplied = request.headers.get("x-csrf-token")
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        raise HTTPException(403, "CSRF token không hợp lệ")


def check_login_rate(request: Request) -> str:
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    attempts = login_attempts[client]
    while attempts and now - attempts[0] > settings.login_window_seconds:
        attempts.popleft()
    if not attempts:
        login_attempts.pop(client, None)  # tránh dict phình dần theo số IP
    if len(attempts) >= settings.login_max_attempts:
        raise HTTPException(429, "Thử đăng nhập quá nhiều lần, vui lòng chờ một phút")
    return client


def conversation_lock(user_id: str, conversation_id: str | None):
    if not conversation_id:
        return nullcontext()
    key = f"{user_id}:{conversation_id}"
    lock = _conversation_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _conversation_locks[key] = lock
    return lock


def conversation_title_from(safe_prompt: str) -> str:
    """Tiêu đề lấy từ prompt đã mask; không cắt đôi token thành "[PERSON_0"."""
    title = _PARTIAL_TOKEN.sub("", safe_prompt[:60]).rstrip()
    return title or "Phiên mới"


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request, "index.html",
        {
            "user": request.session.get("username"),
            "asset_version": asset_version(),
            "max_input_chars": settings.ai_max_input_chars,
        },
    )


def asset_version() -> str:
    """Đổi theo thời điểm sửa JS/CSS để trình duyệt không dùng bản cũ trong cache."""
    static = ROOT / "app" / "static"
    return str(int(max((static / name).stat().st_mtime for name in ("app.js", "style.css"))))


@app.get("/health")
async def health():
    return {"status": "ok", "version": app.version, "mode": settings.ai_mode}


@app.post("/api/auth/login")
async def login(body: LoginBody, request: Request):
    client = check_login_rate(request)
    user = get_user(body.username)
    password_ok = verify_password(body.password, user["password_hash"] if user else _DUMMY_PASSWORD_HASH)
    if not user or not password_ok:
        login_attempts[client].append(time.monotonic())
        raise HTTPException(401, "Sai tài khoản hoặc mật khẩu")
    login_attempts.pop(client, None)
    purge_expired()
    request.session.clear()
    csrf_token = secrets.token_urlsafe(32)
    request.session.update({"user_id": user["id"], "username": user["username"], "csrf_token": csrf_token})
    audit(user["id"], "login")
    return {"ok": True, "username": user["username"], "csrf_token": csrf_token}


@app.get("/api/auth/session")
async def auth_session(request: Request):
    user = current_user(request)
    token = request.session.get("csrf_token") or secrets.token_urlsafe(32)
    request.session["csrf_token"] = token
    return {"username": user["username"], "csrf_token": token}


@app.post("/api/auth/logout")
async def logout(request: Request):
    current_user(request)
    require_csrf(request)
    request.session.clear()
    return {"ok": True}


@app.post("/api/analyze")
async def analyze(body: AnalyzeBody, request: Request):
    current_user(request)
    require_csrf(request)
    detections = detect(body.prompt)
    decision = decide(detections)
    safe_prompt, _ = (
        mask(body.prompt, detections, reserved_tokens=tokens_in([body.prompt]))
        if detections else (body.prompt, {})
    )
    return {
        "action": decision.action,
        "reason": decision.reason,
        "safe_prompt": None if decision.action == "block" else safe_prompt,
        "detections": [item.public() for item in detections],
    }


@app.post("/api/chat")
async def chat(body: ChatBody, request: Request):
    user = current_user(request)
    require_csrf(request)
    started = time.perf_counter()
    detections = detect(body.prompt)
    return await _run_chat(user, body, detections, started)


async def _run_chat(user: dict, body: "ChatBody", detections, started: float) -> dict:
    decision = decide(detections)
    pii_types = sorted({item.kind for item in detections})
    if decision.action == "block":
        audit(user["id"], "chat", policy_action="block", pii_types=pii_types, detail=decision.reason)
        return {"status": "blocked", "action": "block", "reason": decision.reason, "detections": [d.public() for d in detections]}
    purge_expired()
    async with conversation_lock(user["id"], body.conversation_id):
        return await _answer(user, body, detections, decision, pii_types, started)


async def _answer(user: dict, body: ChatBody, detections, decision, pii_types: list[str], started: float) -> dict:
    conversation_id = body.conversation_id
    conversation_title: str | None = None
    history: list[dict] = []
    existing_mapping: dict[str, str] = {}
    # Token đã dùng trong phiên (kể cả token PII do AI tự sinh, không có trong
    # Vault) và token người dùng tự gõ vào prompt đều phải được giữ chỗ.
    reserved = tokens_in([body.prompt])
    if conversation_id:
        conv = get_conversation(user["id"], conversation_id)
        if not conv:
            raise HTTPException(404, "Không tìm thấy phiên hoặc bạn không có quyền truy cập")
        conversation_title = conv["title"]
        history = [{"role": m["role"], "content_sanitized": m["content_sanitized"]} for m in conv["messages"]]
        reserved |= tokens_in(m["content_sanitized"] for m in conv["messages"])
        existing_mapping = token_vault.load(user["id"], conversation_id)

    safe_prompt, current_mapping = (
        mask(body.prompt, detections, reserved_tokens=reserved, known=existing_mapping)
        if detections else (body.prompt, {})
    )

    cross_session_history: list[dict] = []
    if (
        body.use_cross_session_memory
        and settings.memory_enabled
        and settings.cross_session_memory_enabled
    ):
        cross_session_history = get_cross_session_memory(
            user["id"],
            exclude_conversation_id=conversation_id,
            limit=settings.cross_session_memory_messages,
        )
        # Token của phiên khác trùng tên với token phiên này ([PERSON_01] ở hai
        # phiên là hai người khác nhau), nên đổi thành nhãn để không khôi phục nhầm.
        for item in cross_session_history:
            item["content_sanitized"] = label_tokens(item["content_sanitized"])
    # Dành chỗ rõ ràng cho cả ký ức chéo phiên và hội thoại hiện tại.
    max_history = max(0, settings.memory_recent_messages)
    cross_slots = min(len(cross_session_history), settings.cross_session_memory_messages, max_history)
    if history and cross_slots == max_history and max_history:
        cross_slots -= 1
    current_slots = max_history - cross_slots
    cross_session_history = cross_session_history[-cross_slots:] if cross_slots else []
    history = cross_session_history + (history[-current_slots:] if current_slots else [])

    try:
        ai_result = await router.generate(safe_prompt, history, decision.sensitive)
    except RuntimeError as exc:
        audit(user["id"], "chat", policy_action=decision.action, pii_types=pii_types, detail=str(exc))
        raise HTTPException(503, "Không có AI provider khả dụng") from exc
    authorized_mapping = {**existing_mapping, **current_mapping}
    safe_output, output_pii = sanitize_output(
        ai_result.text,
        reserved_tokens=reserved | set(authorized_mapping),
        known=authorized_mapping,
    )
    # Output Scanner luôn chạy trước. Sau đó chỉ token thuộc đúng user/phiên
    # mới được khôi phục để hiển thị; bản lưu và lịch sử gửi AI vẫn đã mask.
    # Token còn lại (PII do AI tự sinh) hiển thị thành nhãn dễ đọc.
    display_output = label_tokens(restore_tokens(safe_output, authorized_mapping))
    if body.remember and settings.memory_enabled:
        if not conversation_id:
            conversation_title = conversation_title_from(safe_prompt)
            conversation_id = create_conversation(user["id"], conversation_title, True)
        token_vault.store(user["id"], conversation_id, current_mapping)
        save_message(conversation_id, "user", safe_prompt, policy_action=decision.action, pii_types=pii_types)
        save_message(
            conversation_id, "assistant", safe_output, provider=ai_result.provider,
            model=ai_result.model, policy_action="output_scan", pii_types=output_pii,
            fallback_reason=ai_result.fallback_reason,
        )

    latency_ms = int((time.perf_counter() - started) * 1000)
    audit(
        user["id"], "chat", policy_action=decision.action, provider=ai_result.provider,
        pii_types=pii_types, latency_ms=latency_ms, detail=ai_result.fallback_reason,
    )
    return {
        "status": "ok", "action": decision.action, "reason": decision.reason,
        "safe_prompt": safe_prompt, "response": display_output,
        "response_sanitized": safe_output, "conversation_id": conversation_id,
        "conversation_title": conversation_title,
        "provider": ai_result.provider, "model": ai_result.model,
        "fallback_reason": ai_result.fallback_reason, "output_pii_types": output_pii,
        "detections": [d.public() for d in detections], "latency_ms": latency_ms,
        "cross_session_memory_used": len(cross_session_history),
    }


@app.get("/api/conversations")
async def conversations(request: Request):
    user = current_user(request)
    return list_conversations(user["id"])


@app.get("/api/conversations/{conversation_id}")
async def conversation(conversation_id: str, request: Request):
    user = current_user(request)
    result = get_conversation(user["id"], conversation_id)
    if not result:
        raise HTTPException(404, "Không tìm thấy phiên")
    mapping = token_vault.load(user["id"], conversation_id)
    for message in result["messages"]:
        message["content_display"] = label_tokens(restore_tokens(message["content_sanitized"], mapping))
    return result


@app.delete("/api/conversations/{conversation_id}")
async def remove_conversation(conversation_id: str, request: Request):
    user = current_user(request)
    require_csrf(request)
    if not delete_conversation(user["id"], conversation_id):
        raise HTTPException(404, "Không tìm thấy phiên")
    audit(user["id"], "delete_conversation")
    return {"ok": True}


@app.get("/api/ai/health")
async def ai_health(request: Request):
    current_user(request)
    return {"mode": settings.ai_mode, "providers": await router.health()}


@app.get("/api/ai/routes")
async def ai_routes(request: Request):
    user = current_user(request)
    return statistics(user["id"])["routes"]


@app.get("/api/statistics")
async def stats(request: Request):
    user = current_user(request)
    return statistics(user["id"])


# ---------------------------------------------------------------------------
# Image Guard: ảnh được OCR và che ngay trên máy chạy gateway. Ảnh gốc không được
# lưu và không được gửi đi; AI chỉ nhận chữ đã che (cùng đường đi với /api/chat).
# ---------------------------------------------------------------------------

async def _read_image(file: UploadFile) -> ImageReport:
    data = await file.read(MAX_IMAGE_BYTES + 1)
    if not ocr_available():
        raise HTTPException(503, "Máy chạy gateway chưa cài Tesseract OCR")
    try:
        report = await asyncio.to_thread(analyze_image, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except OCRUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return report


def _image_summary(report: ImageReport) -> dict:
    return {
        "width": report.width, "height": report.height,
        "redacted_image": "data:image/png;base64," + base64.b64encode(report.redacted_png).decode(),
        "boxes": report.boxes, "qr_codes": report.qr_codes,
        "id_document": report.id_document, "exif_removed": report.exif_removed,
        "gps_removed": report.gps_removed, "ocr_fixes": report.ocr_fixes,
        "timings_ms": report.timings_ms,
    }


def _image_prompt(question: str, ocr_text: str) -> str:
    question = question.strip() or "Hãy tóm tắt nội dung ảnh này."
    header = "\n\n[Nội dung chữ trích từ ảnh người dùng gửi]\n"
    room = max(0, settings.ai_max_input_chars - len(question) - len(header))
    return question + header + ocr_text[:room]


@app.post("/api/image/analyze")
async def image_analyze(request: Request, file: UploadFile = File(...)):
    """Xem trước: ảnh đã che, các vùng PII, QR, EXIF. Không gọi AI."""
    user = current_user(request)
    require_csrf(request)
    report = await _read_image(file)
    detections = report.detections
    decision = decide(detections)
    safe_text, _ = (
        mask(report.ocr_text, detections, reserved_tokens=tokens_in([report.ocr_text]))
        if detections else (report.ocr_text, {})
    )
    audit(user["id"], "image_analyze", policy_action=decision.action,
          pii_types=sorted({d.kind for d in detections} | ({"QR_CODE"} if report.qr_codes else set())))
    return {
        "action": decision.action, "reason": decision.reason,
        "safe_text": None if decision.action == "block" else safe_text,
        "detections": [d.public() for d in detections],
        **_image_summary(report),
    }


@app.post("/api/image/chat")
async def image_chat(
    request: Request,
    file: UploadFile = File(...),
    question: str = Form("", max_length=1000),
    conversation_id: str | None = Form(None, max_length=64),
    remember: bool = Form(True),
    use_cross_session_memory: bool = Form(True),
):
    """Hỏi AI về ảnh: chỉ chữ đã che trong ảnh được gửi đi, theo đúng luồng chat."""
    user = current_user(request)
    require_csrf(request)
    started = time.perf_counter()
    report = await _read_image(file)
    try:
        body = ChatBody(
            prompt=_image_prompt(question, report.ocr_text), conversation_id=conversation_id or None,
            remember=remember, use_cross_session_memory=use_cross_session_memory,
        )
    except ValidationError as exc:
        raise HTTPException(422, "Ảnh không có chữ đọc được và câu hỏi trống") from exc
    # Nhận diện lại trên toàn prompt (câu hỏi + chữ OCR) bằng bộ dò dành cho OCR,
    # để vùng chỉ bắt được qua lượt bỏ dấu cũng được che khi gửi AI.
    result = await _run_chat(user, body, detect_ocr_text(body.prompt), started)
    result["image"] = _image_summary(report)
    return result
