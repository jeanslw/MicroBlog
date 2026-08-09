"""Flask 扩展实例集中点。

所有扩展在此创建实例（但不绑定 app），工厂在 create_app() 时统一 init_app。
这样避免循环导入，并使测试可重用实例。
"""
import logging
import time
from datetime import timedelta
from functools import wraps
from urllib.parse import urlparse

from flask import current_app, request, session, flash, redirect, url_for
from flask_login import LoginManager, current_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

# 扩展实例（不绑定 app）
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

# 登录视图、消息
login_manager.login_view = "admin.login"
login_manager.login_message_category = "warning"


# ── 全局日志（独立于 Flask logger，便于扩展模块复用） ─────────
log = logging.getLogger("blog")


# ── LoginManager 加载用户回调 ────────────────────────────
@login_manager.user_loader
def load_user(user_id: str):
    from app.models import Admin
    try:
        return db.session.get(Admin, int(user_id))
    except (TypeError, ValueError):
        return None


# ── 真实客户端 IP（信任 ProxyFix 设置的 remote_addr） ──────
def get_client_ip() -> str:
    """获取客户端真实 IP。

    必须在 create_app() 中通过 ProxyFix 配置可信代理层数后,
    `request.remote_addr` 才会反映 X-Forwarded-For 链中正确的位置。
    严禁直接读取 request.headers['X-Forwarded-For']——客户端可伪造。
    """
    return request.remote_addr or "unknown"


# ── 登录防爆破（基于数据库表，多 worker 共享） ────────────
# 设计：用 login_attempt 表持久化 (ip, username) → fail_count, lock_until
# 避免 extensions.py 早期依赖 models,这里用惰性导入

def check_login_lock(ip: str, username: str):
    """检查登录是否被锁定,返回 (locked, remain_seconds)"""
    from app.models import LoginAttempt
    try:
        rec = db.session.execute(
            db.select(LoginAttempt).filter_by(ip=ip, username=username)
        ).scalar_one_or_none()
    except Exception:
        # 表尚未建立（首次启动前）或 DB 异常,放行避免阻断
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
    """记录一次登录失败,达阈值则锁定。返回当前失败次数。

    DB 异常时不阻断登录流程,仅告警（与 check_login_lock 的容错策略一致）。
    """
    from app.models import LoginAttempt
    try:
        rec = db.session.execute(
            db.select(LoginAttempt).filter_by(ip=ip, username=username)
        ).scalar_one_or_none()
        if not rec:
            rec = LoginAttempt(ip=ip, username=username, fail_count=0, lock_until=0)
            db.session.add(rec)
        rec.fail_count += 1
        if rec.fail_count >= 5:
            rec.lock_until = time.time() + lock_seconds
        db.session.commit()
        return rec.fail_count
    except Exception:
        db.session.rollback()
        log.warning("record_login_fail 失败,跳过记录", exc_info=True)
        return 0


def clear_login_fail(ip: str, username: str):
    """登录成功后清除失败记录"""
    from app.models import LoginAttempt
    try:
        rec = db.session.execute(
            db.select(LoginAttempt).filter_by(ip=ip, username=username)
        ).scalar_one_or_none()
        if rec:
            db.session.delete(rec)
            db.session.commit()
    except Exception:
        db.session.rollback()
        log.warning("clear_login_fail 失败,跳过清除", exc_info=True)


# ── 视图层装饰器 ─────────────────────────────────────────
def admin_required(f):
    """装饰器：要求管理员登录（基于 Flask-Login current_user）"""
    from flask_login import login_required

    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        from app.models import Admin
        if not isinstance(current_user, Admin):
            flash("请先登录管理员账号", "warning")
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return decorated


# ── 全局上下文数据（每页面查询一次,带异常兜底） ────────────
def fetch_global_context():
    """获取全局模板数据：栏目 + 总数 + 轮播 + 站点名。

    使用 current_app.app_context() 内的 db.session,
    DB 异常时返回默认值避免页面整页崩溃。
    """
    from app.models import Category, Article, Banner, SiteConfig
    try:
        cats = db.session.execute(
            db.select(
                Category.id, Category.cat_name, Category.tag_text,
                Category.create_time,
                db.func.count(Article.id).label("art_count"),
            )
            .outerjoin(Article, db.and_(Category.id == Article.category_id,
                                         Article.status == "publish"))
            .group_by(Category.id)
            .order_by(Category.id.desc())
        ).all()
        total_art = db.session.scalar(
            db.select(db.func.count(Article.id)).filter(Article.status == "publish")
        ) or 0
        banner_list = db.session.execute(
            db.select(Banner).order_by(Banner.sort.desc())
        ).scalars().all()
        site_name = db.session.scalar(db.select(SiteConfig.site_name)) or "博客"
    except Exception:
        log.error("全局模板上下文数据库报错", exc_info=True)
        cats, total_art, banner_list, site_name = [], 0, [], "博客"
    return {
        "categories": cats,
        "all_article_count": total_art,
        "site_name": site_name,
        "banner_list": banner_list,
    }


# ── 工具：URL 安全拼接（防止 link_url 注入 javascript:） ────
def safe_url(url: str) -> str:
    """对外链做协议白名单校验，非 http(s) 返回空串"""
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme in ("http", "https"):
            return url
    except ValueError:
        pass
    # 自动补全 https://
    if url and not url.startswith(("http://", "https://")):
        return "https://" + url
    return ""
