"""Flask 扩展实例集中点：在此创建扩展实例，由 create_app() 统一 init_app。"""

import logging
import time
from datetime import datetime
from functools import wraps
from urllib.parse import urlparse, urlsplit

from flask import current_app, flash, redirect, request, url_for
from flask_babel import _
from flask_babel import lazy_gettext as _l
from flask_login import LoginManager, current_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

from app.utils import asset_url_exists

# 扩展实例(不绑定 app)
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

login_manager.login_view = "admin.login"
login_manager.login_message_category = "warning"


log = logging.getLogger("blog")


@login_manager.user_loader
def load_user(user_id: str):
    from app.models import Admin

    try:
        return db.session.get(Admin, int(user_id))
    except (TypeError, ValueError):
        return None
    except Exception as e:
        # 必须 rollback：查询失败后 Session 处于待回滚态，
        # 不清掉的话同请求后续任何查询都会抛 PendingRollbackError
        db.session.rollback()
        log.warning("load_user 查询失败,降级为匿名: %s", e)
        return None


def get_client_ip() -> str:
    """获取客户端真实 IP；须先由 ProxyFix 配置可信代理层数。"""
    return request.remote_addr or "unknown"


def external_url_for(endpoint: str, **values) -> str:
    """生成绝对 URL，优先使用 CANONICAL_URL；未配置时回退 request.host_url。"""
    from flask import current_app

    canonical = (current_app.config.get("CANONICAL_URL") or "").rstrip("/")
    if canonical:
        # 以 CANONICAL_URL 为基准拼接相对路径，保证 scheme 与 host 可信
        from urllib.parse import urljoin

        return urljoin(canonical + "/", url_for(endpoint, **values).lstrip("/"))
    return url_for(endpoint, _external=True, **values)


def check_login_lock(ip: str, username: str):
    """检查登录是否被锁定,返回 (locked, remain_seconds)"""
    from app.models import LoginAttempt

    try:
        rec = db.session.execute(db.select(LoginAttempt).filter_by(ip=ip, username=username)).scalar_one_or_none()
    except Exception:
        # DB 异常时放行
        log.warning("login_lock 查询失败,放行", exc_info=True)
        return False, 0

    if not rec:
        return False, 0
    if rec.fail_count >= 5 and rec.lock_until and time.time() < rec.lock_until:
        return True, int(rec.lock_until - time.time())
    # 锁定已过期,自动清零
    if rec.fail_count >= 5 and rec.lock_until and time.time() >= rec.lock_until:
        db.session.delete(rec)
        db.session.commit()
    return False, 0


def record_login_fail(ip: str, username: str, lock_seconds: int = 300) -> int:
    """记录一次登录失败，达阈值则锁定；返回当前失败次数。"""
    from app.models import LoginAttempt

    try:
        rec = db.session.execute(db.select(LoginAttempt).filter_by(ip=ip, username=username)).scalar_one_or_none()
        if not rec:
            rec = LoginAttempt(ip=ip, username=username, fail_count=0, lock_until=0)
            db.session.add(rec)
        rec.fail_count += 1
        rec.update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if rec.fail_count >= 5:
            rec.lock_until = time.time() + lock_seconds
        db.session.commit()
        # Column[int] 运行时即 int
        return rec.fail_count  # type: ignore[return-value]
    except Exception:
        db.session.rollback()
        log.warning("record_login_fail 失败,跳过记录", exc_info=True)
        return 0


def clear_login_fail(ip: str, username: str):
    """登录成功后清除失败记录"""
    from app.models import LoginAttempt

    try:
        rec = db.session.execute(db.select(LoginAttempt).filter_by(ip=ip, username=username)).scalar_one_or_none()
        if rec:
            db.session.delete(rec)
            db.session.commit()
    except Exception:
        db.session.rollback()
        log.warning("clear_login_fail 失败,跳过清除", exc_info=True)


def admin_required(f):
    """装饰器:要求管理员登录(基于 Flask-Login current_user)"""
    from flask_login import login_required

    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        from app.models import Admin

        if not isinstance(current_user, Admin):
            flash(_("请先登录管理员账号"), "warning")
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)

    return decorated


def _default_global_context():
    """全局模板的默认值(DB 不可用 / 维护模式待迁移时使用)."""
    return {
        "categories": [],
        "all_article_count": 0,
        "site_name": "博客",
        "site_logo": "",
        "site_favicon": "",
        "about_nickname": "",
        "banner_list": [],
        "site_bg_style": "bg1",
        "site_bg_custom": "",
        "comments_enabled": True,
        "site_sidebar_style": "book",
    }


def fetch_global_context():
    """获取全局模板数据：栏目 + 总数 + 轮播 + 站点名；DB 异常时返回默认值。"""
    try:
        if current_app.config.get("SCHEMA_UPGRADE_PENDING"):
            return _default_global_context()
    except RuntimeError:
        pass  # 无应用上下文(CLI 场景),走正常查询路径

    from app.database import get_about_profile, get_site_setting
    from app.models import Article, Banner, Category

    try:
        cats = db.session.execute(
            db.select(
                Category.id,
                Category.cat_name,
                Category.tag_text,
                Category.create_time,
                db.func.count(Article.id).label("art_count"),
            )
            .outerjoin(Article, db.and_(Category.id == Article.category_id, Article.status == "publish"))
            .group_by(Category.id)
            .order_by(Category.id.desc())
        ).all()
        total_art = db.session.scalar(db.select(db.func.count(Article.id)).filter(Article.status == "publish")) or 0
        banner_list = (
            db.session.execute(db.select(Banner).filter(Banner.is_active.is_(True)).order_by(Banner.sort.desc()))
            .scalars()
            .all()
        )
        # 站点配置与「关于我」各读一次（v1.3.6 起拆分自 site_config）
        site = get_site_setting()
        site_name = (site.site_name or "博客") if site else "博客"
        site_logo = (site.logo_path or "") if site else ""
        # 文件缺失时回落为无 Logo，避免破图
        if not asset_url_exists(site_logo):
            site_logo = ""
        site_favicon = (site.favicon_path or "") if site else ""
        # 相对路径转为可访问的 URL
        if site_favicon and not site_favicon.startswith(("http://", "https://")):
            site_favicon = "/" + site_favicon.lstrip("/")
        about_nickname = ""
        about = get_about_profile()
        if about is not None:
            about_nickname = about.about_nickname or ""
        site_bg_style = (site.bg_style or "bg1") if site else "bg1"
        site_bg_custom = (site.bg_custom or "") if site else ""
        raw_comments_enabled = site.comments_enabled if site else None
        comments_enabled = True if raw_comments_enabled is None else bool(raw_comments_enabled)
        site_sidebar_style = (site.sidebar_style or "book") if site else "book"
    except Exception:
        # 同 load_user：先 rollback 再降级，否则后续渲染查询全部失败
        db.session.rollback()
        log.error("全局模板上下文数据库报错", exc_info=True)
        return _default_global_context()
    return {
        "categories": cats,
        "all_article_count": total_art,
        "site_name": site_name,
        "site_logo": site_logo,
        "site_favicon": site_favicon,
        "about_nickname": about_nickname,
        "banner_list": banner_list,
        "site_bg_style": site_bg_style,
        "site_bg_custom": site_bg_custom,
        "comments_enabled": comments_enabled,
        "site_sidebar_style": site_sidebar_style,
    }


def safe_url(url: str) -> str:
    """对外链做协议白名单校验：仅 http(s) 直通，无协议时补 https://，其余返回空串。"""
    if not url:
        return ""
    candidate = url.strip()
    if not candidate:
        return ""
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return ""
    if parsed.scheme:
        return candidate if parsed.scheme in ("http", "https") else ""
    # 无协议时补 https://，并要求能解析出主机名
    try:
        host = urlsplit("//" + candidate).hostname or ""
    except ValueError:
        return ""
    if not host:
        return ""
    return "https://" + candidate


def safe_redirect_path(target: str | None) -> str | None:
    """把用户可控的跳转目标(next 参数 / Referer)收敛为站内相对路径.

    返回值保证以常量 "/" 开头,不含 scheme/netloc/反斜杠,可直接用于
    redirect() 而不会跳出本站;输入不可用(空/外站)时返回 None.
    用户输入只作为常量前缀 "/" 的右操作数参与拼接,不构成 URL 前缀.
    """
    if not target or not target.strip():
        return None
    try:
        parts = urlsplit(target.strip())
    except ValueError:
        return None
    # 拒绝非 http(s) 的伪协议（如 javascript:、data:）
    if parts.scheme and parts.scheme not in ("http", "https"):
        return None
    # 带主机名的完整 URL 仅放行同源
    if parts.netloc and parts.netloc != request.host:
        return None
    # 剥掉前导斜杠与反斜杠后统一补回常量前缀 "/"，杜绝 //evil.com、/\evil.com
    safe = "/" + parts.path.lstrip("/\\").replace("\\", "/")
    if parts.query:
        safe += "?" + parts.query
    return safe


# 字段名 -> 本地化标签
_FIELD_LABEL_KEYS = {
    "username": _l("用户名"),
    "content": _l("内容"),
    "cat_name": _l("栏目名称"),
    "tag_text": _l("标签"),
    "banner_img": _l("轮播图"),
    "link_url": _l("跳转链接"),
    "title": _l("标题"),
    "desc_text": _l("描述"),
    "sort_num": _l("排序"),
    "mail_host": _l("SMTP 服务器"),
    "mail_port": _l("端口"),
    "mail_user": _l("用户名"),
    "mail_password": _l("密码"),
    "mail_from": _l("发件人邮箱"),
    "site_name": _l("站点名称"),
    "about_nickname": _l("昵称"),
    "about_email": _l("邮箱"),
    "about_github": _l("GitHub 链接"),
    "about_homepage": _l("个人主页"),
    "about_bio": _l("个人简介"),
}


def flash_form_errors(form) -> None:
    """把 WTForms 校验错误以'字段标签: 错误'形式 flash 出来,字段名已本地化."""
    for field, errs in form.errors.items():
        label = _FIELD_LABEL_KEYS.get(field, field)
        for err in errs:
            flash(f"{_(label)}: {err}", "danger")


def _rate_limit_window_str(window_seconds: int) -> str:
    """返回窗口起始时间的字符串(与 create_time 同格式,便于字符串比较)"""
    return datetime.fromtimestamp(time.time() - window_seconds).strftime("%Y-%m-%d %H:%M:%S")


def check_and_record_rate_limit(action: str, ip: str, limit: int, window_seconds: int = 300) -> bool:
    """检查并记录一次频率限制，返回 True 表示允许。"""
    from app.models import RateLimit

    try:
        threshold = _rate_limit_window_str(window_seconds)
        # 惰性清理窗口外的旧记录，单独提交，避免被超限回滚一并撤销
        db.session.execute(db.delete(RateLimit).where(RateLimit.action == action, RateLimit.create_time < threshold))
        db.session.commit()
        count = (
            db.session.scalar(
                db.select(db.func.count(RateLimit.id)).where(
                    RateLimit.action == action,
                    RateLimit.ip == ip,
                    RateLimit.create_time >= threshold,
                )
            )
            or 0
        )
        if count >= limit:
            return False
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.session.add(RateLimit(ip=ip, action=action, create_time=now))
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        log.warning("rate_limit 查询失败,放行 action=%s ip=%s", action, ip, exc_info=True)
        return True


def rate_limit(action: str, limit: int = 10, window_seconds: int = 300):
    """视图装饰器：按 IP 限制动作频率，超限则回退到来源页或首页。"""

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            ip = get_client_ip()
            if not check_and_record_rate_limit(action, ip, limit, window_seconds):
                flash(_("操作过于频繁，请 %(min)s 分钟后再试", min=max(1, window_seconds // 60)), "warning")
                return redirect(safe_redirect_path(request.referrer) or url_for("blog.index"))
            return f(*args, **kwargs)

        return decorated

    return decorator
