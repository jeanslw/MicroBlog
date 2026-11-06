"""邮件发送工具：SMTP 配置只从系统设置读取，使用 stdlib smtplib + email.message。"""

import contextlib
import smtplib
from email.message import EmailMessage

from app.crypto import decrypt_secret
from app.settings import get_system_setting


class MailError(Exception):
    """邮件发送失败(未配置或 SMTP 错误)."""


def send_mail(to: str, subject: str, body: str) -> None:
    """发送纯文本邮件；SMTP 未配置或发送失败抛 MailError。"""
    setting = get_system_setting()
    if setting is None:
        raise MailError("邮件服务未配置")

    host = (setting.mail_host or "").strip()
    port = int(setting.mail_port or 587)
    user = (setting.mail_user or "").strip()
    password = decrypt_secret(setting.mail_password or "")
    sender = (setting.mail_from or "").strip() or user
    use_ssl = bool(setting.mail_use_ssl)
    use_tls = bool(setting.mail_use_tls)

    if not host or not sender:
        raise MailError("邮件服务未配置")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body)

    server: smtplib.SMTP | None = None
    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            if use_tls:
                server.starttls()
        if user:
            server.login(user, password)
        server.send_message(msg)
    except Exception as e:
        raise MailError(str(e)) from e
    finally:
        if server is not None:
            with contextlib.suppress(Exception):
                server.quit()
