"""邮件发送工具（找回密码）。

使用 stdlib smtplib + email.message，不引入第三方依赖。
SMTP 配置从 app.config 读取（对应 .env 的 BLOG_MAIL_*），
未配置或发送失败抛 MailError，由调用方捕获后提示用户。
"""

import contextlib
import smtplib
from email.message import EmailMessage

from flask import current_app

from app.crypto import decrypt_secret


class MailError(Exception):
    """邮件发送失败（未配置或 SMTP 错误）。"""


def send_mail(to: str, subject: str, body: str) -> None:
    """发送纯文本邮件。SMTP 未配置或发送失败抛 MailError。

    优先使用后台保存的 SMTP 配置（site_config.mail_host 非空即视为已配置），
    否则回退到环境变量（.env 的 BLOG_MAIL_*）。
    """
    cfg = current_app.config

    # 后台保存的 SMTP 配置优先；未配置则回退到环境变量
    db_host = ""
    site = None
    try:
        from app.extensions import db
        from app.models import SiteConfig

        site = db.session.get(SiteConfig, 1)
        db_host = (site.mail_host or "").strip() if site else ""
    except Exception:
        site = None

    if db_host:
        host = db_host
        port = int(site.mail_port or 587)
        user = site.mail_user or ""
        password = decrypt_secret(site.mail_password or "")
        sender = site.mail_from or user
        use_ssl = bool(site.mail_use_ssl)
        use_tls = bool(site.mail_use_tls)
    else:
        host = cfg.get("MAIL_HOST", "")
        port = int(cfg.get("MAIL_PORT", 587) or 587)
        user = cfg.get("MAIL_USER", "")
        password = cfg.get("MAIL_PASSWORD", "")
        sender = cfg.get("MAIL_FROM", "") or user
        use_ssl = bool(cfg.get("MAIL_USE_SSL", False))
        use_tls = bool(cfg.get("MAIL_USE_TLS", True))

    if not host or not sender:
        raise MailError("邮件服务未配置")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body)

    server = None
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
