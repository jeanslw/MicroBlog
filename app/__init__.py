"""Flask 应用工厂。

集成：
- Flask-SQLAlchemy（ORM + 连接池）
- Flask-Migrate（迁移）
- Flask-Login（会话与认证）
- Flask-WTF（CSRF + 表单）
- Flask-Babel（i18n 中英双语）
- ProxyFix（信任反向代理头）
- 完整错误处理（区分 HTTPException 与 Exception）
- 启动时自动初始化数据库与管理员
- Flask CLI 命令（init-db / create-admin）
"""

import logging
import os
import traceback
from datetime import date, timedelta

from flask import Flask, current_app, jsonify, render_template, request, session
from flask_babel import Babel, _
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from app.extensions import (
    csrf,
    db,
    fetch_global_context,
    log,
    login_manager,
)
from app.utils import configure_pillow
from config import APP_VERSION, get_config


def _is_trusted_host(host: str | None) -> bool:
    """校验请求 Host 是否在白名单内（BLOG_TRUSTED_HOSTS）。

    白名单为空时放行（仅开发便捷）；生产环境应配置真实域名。
    去除端口后再比对，支持 IPv6（带方括号）。
    """
    if not host:
        return False
    # 去除端口（兼容 IPv6 的 [::1]:5000 形式）
    host_only = host.split("]", 1)[0] + "]" if host.startswith("[") else host.split(":", 1)[0]
    trusted = current_app.config.get("TRUSTED_HOSTS") or []
    if not trusted:
        return True  # 未配置白名单时放行
    return host_only.lower() in trusted


def _setup_logging(app: Flask):
    """统一日志格式"""
    if not app.logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s in %(module)s: %(message)s"))
        app.logger.addHandler(handler)
    app.logger.setLevel(logging.DEBUG if app.debug else logging.INFO)
    # 让 app.extensions.log 也跟随同级别
    log.setLevel(app.logger.level)


def _select_locale():
    """Babel 选 locale：优先 session['lang'],其次 Accept-Language,最后默认"""
    lang = session.get("lang")
    if lang in ("zh_CN", "en"):
        return lang
    # 浏览器偏好
    best = request.accept_languages.best_match(["zh_CN", "en"])
    return best or "zh_CN"


babel = Babel()


def create_app(config_name: str | None = None):
    """应用工厂

    Args:
        config_name: 显式指定配置类（development/production/testing），
                     None 时从环境变量 BLOG_ENV 读取
    """
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    template_dir = os.path.join(root_dir, "templates")
    static_dir = os.path.join(root_dir, "static")

    app = Flask(
        __name__,
        template_folder=template_dir,
        static_folder=static_dir,
        instance_relative_config=False,
    )

    # ── 加载配置 ────────────────────────────────────────
    if config_name:
        from config import config_map

        app.config.from_object(config_map.get(config_name, config_map["default"]))
    else:
        app.config.from_object(get_config())

    # timedelta 形式的 PERMANENT_SESSION_LIFETIME
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
        seconds=int(app.config.get("PERMANENT_SESSION_LIFETIME", 60 * 60 * 12))
    )

    # ── ProxyFix（信任反向代理头） ──────────────────────
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=app.config.get("PROXY_FIX_X_FOR", 0),
        x_proto=app.config.get("PROXY_FIX_X_PROTO", 0),
        x_host=app.config.get("PROXY_FIX_X_HOST", 0),
    )

    # ── Pillow 安全配置 ─────────────────────────────────
    configure_pillow(app.config.get("PIL_MAX_IMAGE_PIXELS", 50_000_000))

    # ── 扩展初始化 ──────────────────────────────────────
    db.init_app(app)
    try:
        from flask_migrate import Migrate

        Migrate(app, db, directory=os.path.join(root_dir, "migrations"))
    except ImportError:
        log.warning("Flask-Migrate 未安装,跳过迁移支持")

    login_manager.init_app(app)
    csrf.init_app(app)
    babel.init_app(app, locale_selector=_select_locale)

    _setup_logging(app)

    # 注：CSRFProtect 默认仅对 POST/PUT/DELETE/PATCH 校验,
    # GET 静态文件请求与 favicon 不会被拦截,无需显式豁免

    # ── 启动时初始化数据库与初始数据 ────────────────────
    with app.app_context():
        from app.database import ensure_admin_exists, ensure_site_config, init_db

        try:
            init_db()
            ensure_site_config()
            ensure_admin_exists()
        except Exception as e:
            app.logger.warning("数据库初始化跳过: %s", e)

    # ── 模板全局变量（每页面一次,带异常兜底） ─────────────
    # 注:不在此注入 csrf_token —— Flask-WTF 通过 jinja_env.globals
    # 注册了 csrf_token() 函数,模板用 {{ csrf_token() }} 调用即可。
    # 此处若注入字符串 csrf_token 会遮蔽该函数。
    @app.context_processor
    def global_vars():
        ctx = fetch_global_context()
        ctx.update(
            {
                "now_year": date.today().year,
                "current_lang": _select_locale(),
                "app_version": APP_VERSION,
            }
        )
        return ctx

    # ── 错误处理 ────────────────────────────────────────
    def _safe_error_page(code: int, message: str):
        """渲染错误页；模板/上下文自身出错时退回纯 HTML,保证错误处理永不二次抛错。"""
        try:
            return render_template("error.html", code=code, message=message), code
        except Exception:
            return f"<h1>{code}</h1><p>{message}</p>", code

    @app.errorhandler(HTTPException)
    def http_error_handler(e):
        # HTTP 异常按状态码返回对应页面,不吞成 500
        code = e.code or 500
        if request.path.startswith("/admin/upload") or request.is_json:
            return jsonify({"error": e.description}), code
        return _safe_error_page(code, e.description)

    @app.errorhandler(400)
    def bad_request(e):
        if request.is_json:
            return jsonify({"error": str(e.description or e)}), 400
        return _safe_error_page(400, str(e.description or e))

    @app.errorhandler(404)
    def not_found(e):
        if request.is_json:
            return jsonify({"error": "Not Found"}), 404
        return _safe_error_page(404, _("页面不存在"))

    @app.errorhandler(Exception)
    def all_err_handler(e):
        log.error("未捕获异常: %s", e)
        log.error(traceback.format_exc())
        if app.debug:
            return traceback.format_exc(), 500
        if request.is_json:
            return jsonify({"error": "服务器内部错误"}), 500
        return _safe_error_page(500, _("服务器内部错误,请联系管理员"))

    # ── Host 白名单校验（防 Host 头注入 / 密码重置邮件投毒） ─
    @app.before_request
    def _validate_host():
        # 静态文件、健康检查等放行；其余非白名单 Host 返回 400
        if request.endpoint == "static":
            return None
        if not _is_trusted_host(request.host):
            app.logger.warning("拒绝非白名单 Host 请求: %s (ip=%s)", request.host, request.remote_addr)
            return jsonify({"error": "Invalid Host header"}), 400

    # ── 注册蓝图 ────────────────────────────────────────
    from app.admin import admin_bp
    from app.banner import banner_bp
    from app.blog import blog_bp
    from app.comment import comment_bp
    from app.main import main_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(blog_bp)
    app.register_blueprint(comment_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(banner_bp, url_prefix="/banner")

    # ── Flask CLI 命令 ──────────────────────────────────
    register_cli(app)

    return app


def register_cli(app: Flask):
    """注册 flask 命令：init-db / create-admin"""
    import click
    from flask.cli import with_appcontext

    @app.cli.command("init-db")
    @with_appcontext
    def init_db_cmd():
        """创建所有数据库表（幂等）"""
        from app.database import ensure_admin_exists, ensure_site_config, init_db

        init_db()
        ensure_site_config()
        ensure_admin_exists()
        click.echo("Initialized database and ensured admin/site_config.")

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    @with_appcontext
    def create_admin_cmd(username, password):
        """创建管理员账号"""
        from werkzeug.security import generate_password_hash

        from app.models import Admin

        if db.session.scalar(db.select(Admin).filter_by(username=username)):
            click.echo(f"Admin '{username}' already exists.")
            return
        db.session.add(Admin(username=username, password=generate_password_hash(password)))
        db.session.commit()
        click.echo(f"Created admin: {username}")
