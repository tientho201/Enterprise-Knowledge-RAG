"""Celery task gửi email — hiện chỉ dùng cho OTP xác minh đăng ký.

SMTP qua stdlib `smtplib` (sync) — Celery worker chạy sync context nên không cần
client async riêng (không thêm dependency mới). Nếu `SMTP_HOST` rỗng (chưa cấu
hình, vd máy dev) thì bỏ qua gửi thật và chỉ log warning — không raise, giống
cách Neo4j graceful-degrade khi service phụ chưa sẵn sàng.
"""

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.tasks.email.send_otp_email",
    bind=True,
    max_retries=3,
    retry_backoff=True,
)
def send_otp_email(self, to_email: str, otp_code: str, full_name: str | None = None) -> dict:
    if not settings.SMTP_HOST:
        # Dev-only: SMTP_HOST rỗng là lựa chọn chủ động của người chạy local (không
        # cấu hình Gmail), nên in luôn mã OTP ra log worker để test được luồng mà
        # không cần hộp thư thật. KHÔNG áp dụng khi đã cấu hình SMTP_HOST thật.
        logger.warning(
            "SMTP chưa cấu hình (SMTP_HOST rỗng) — bỏ qua gửi thật. Mã OTP cho %s: %s",
            to_email,
            otp_code,
        )
        return {"status": "skipped", "reason": "smtp_not_configured"}

    greeting = f"Chào {full_name}," if full_name else "Xin chào,"
    body = (
        f"{greeting}\n\n"
        f"Mã OTP xác minh đăng ký của bạn là: {otp_code}\n\n"
        f"Mã có hiệu lực trong {settings.OTP_EXPIRE_MINUTES} phút. "
        "Vui lòng không chia sẻ mã này cho bất kỳ ai.\n\n"
        "Nếu bạn không thực hiện yêu cầu đăng ký này, vui lòng bỏ qua email."
    )
    msg = EmailMessage()
    msg["Subject"] = "Mã OTP xác minh đăng ký - Enterprise Knowledge RAG"
    msg["From"] = settings.SMTP_FROM_EMAIL or settings.SMTP_USER
    msg["To"] = to_email
    msg.set_content(body)

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
        logger.info("Đã gửi OTP email tới %s", to_email)
        return {"status": "sent", "to": to_email}
    except Exception as exc:
        logger.error("Gửi OTP email thất bại tới %s: %s", to_email, exc)
        raise self.retry(exc=exc) from exc
