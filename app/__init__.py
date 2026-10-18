"""Flask 应用工厂：集成 SQLAlchemy / Migrate / Login / WTF / Babel / ProxyFix，注册错误处理与 CLI 命令。"""

import logging
import os
import time
import traceback
from datetime import date, timedelta
from logging.handlers import RotatingFileHandler
from urllib.parse import urlsplit

from flask import Flask, current_app, g, jsonify, render_template, request, session
from flask_babel import Babel, _
from flask_login import current_user
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from app.extensions import (
    csrf,
    db,
    fetch_global_context,
    log,
    login_manager,
)
from app.observability import (
    REQUEST_ID_HEADER,
    RequestIdFilter,
    begin_request_id,
    build_formatter,
    end_request_id,
    log_event,
    register_slow_sql,
)
from app.utils import configure_pillow
from config import APP_VERSION, get_config


def _is_trusted_host(host: str | None) -> bool:
    """校验请求 Host 是否在白名单内（BLOG_TRUSTED_HOSTS）；白名单为空时放行，比对前去除端口。"""
    if not host:
        return False
    # 去除端口，兼容 IPv6 的 [::1]:5000 形式
    host_only = host.split("]", 1)[0] + "]" if host.startswith("[") else host.split(":", 1)[0]
    trusted = current_app.config.get("HOST_WHITELIST") or []
    if not trusted:
        return True
    return host_only.lower() in trusted


def _setup_logging(app: Flask):
    """配置统一日志：控制台 + 按大小轮转的文件日志（LOG_DIR/app.log）。"""
    # 非法级别值回退 INFO，不阻断启动
    raw_level = str(app.config.get("LOG_LEVEL") or "auto").upper()
    bad_level = None
    if raw_level in ("", "AUTO"):
        level = logging.DEBUG if app.debug else logging.INFO
    else:
        parsed = getattr(logging, raw_level, None)
        if not isinstance(parsed, int):
            bad_level = raw_level
            parsed = logging.INFO
        level = parsed
    # 生产默认单行 JSON，开发/测试为可读文本；LOG_FORMAT 可强制覆盖
    formatter = build_formatter(app.config.get("LOG_FORMAT", "auto"), debug=app.debug, testing=app.testing)
    req_filter = RequestIdFilter()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(req_filter)
    stream_handler._blog_log_handler = True  # type: ignore[attr-defined]

    file_handler = None
    log_dir = app.config.get("LOG_DIR", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "app.log"),
            maxBytes=int(app.config.get("LOG_MAX_BYTES", 10 * 1024 * 1024)),
            backupCount=int(app.config.get("LOG_BACKUP_COUNT", 5)),
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(req_filter)
        file_handler._blog_log_handler = True  # type: ignore[attr-defined]
    except OSError:
        # 目录不可写时退回仅控制台，不阻断启动
        app.logger.warning("日志目录不可用,文件日志已禁用: %s", log_dir, exc_info=True)

    def _configure(target: logging.Logger):
        # 移除 Flask 自动挂载的 stderr handler，避免每条日志输出两份
        for h in list(target.handlers):
            if type(h) is logging.StreamHandler and not getattr(h, "_blog_log_handler", False):
                target.removeHandler(h)
        if not any(getattr(h, "_blog_log_handler", False) for h in target.handlers):
            target.addHandler(stream_handler)
            if file_handler is not None:
                target.addHandler(file_handler)
        target.setLevel(level)

    _configure(app.logger)
    _configure(log)

    if bad_level:
        app.logger.warning(
            "BLOG_LOG_LEVEL 取值非法(%s)，已回退 INFO；可用值：AUTO/DEBUG/INFO/WARNING/ERROR/CRITICAL",
            bad_level,
        )


def _select_locale():
    """Babel 选 locale:优先 session['lang'],其次 Accept-Language,最后默认"""
    lang = session.get("lang")
    if lang in ("zh_CN", "en"):
        return lang
    # 浏览器偏好
    best = request.accept_languages.best_match(["zh_CN", "en"])
    return best or "zh_CN"


babel = Babel()


def run_startup_schema_migrations(app) -> None:
    """执行启动时的 schema 迁移。

    AUTO_SCHEMA_MIGRATE=false 时不改库，仅置 SCHEMA_UPGRADE_PENDING 标志；
    数据库版本高于程序版本时抛 RuntimeError，ALLOW_SCHEMA_AHEAD=true 时改为告警。
    """
    from app.database import (
        SCHEMA_VERSION,
        get_schema_version,
        pending_schema_migrations,
        run_schema_migrations,
        schema_version_cmp,
    )

    try:
        current = get_schema_version()
    except Exception:
        current = None
    if current and schema_version_cmp(current, SCHEMA_VERSION) > 0:
        if app.config.get("ALLOW_SCHEMA_AHEAD"):
            app.logger.warning(
                "数据库 schema 版本(v%s)高于程序版本(v%s),"
                "BLOG_ALLOW_SCHEMA_AHEAD=true 已放行启动;请尽快完成程序升级或回退数据库",
                current,
                SCHEMA_VERSION,
            )
            return
        raise RuntimeError(
            f"数据库 schema 版本(v{current})高于程序版本(v{SCHEMA_VERSION}):"
            "检测到代码被降级运行。旧代码缺少新结构的迁移知识,继续启动可能误改数据;"
            "请恢复与数据库匹配的程序版本,或用升级前的备份回退数据库。"
            "(如确属滚动升级窗口等受控场景,可临时设 BLOG_ALLOW_SCHEMA_AHEAD=true 放行)"
        )

    try:
        if app.config.get("AUTO_SCHEMA_MIGRATE", True):
            run_schema_migrations()
        else:
            pending = pending_schema_migrations(quiet=True)
            if pending:
                app.config["SCHEMA_UPGRADE_PENDING"] = True
                app.logger.warning(
                    "检测到 %d 项待迁移 schema 且自动迁移已关闭(BLOG_AUTO_MIGRATE=false),"
                    "站点进入维护模式;请管理员登录后在「迁移数据库」页执行迁移",
                    len(pending),
                )
    except Exception as e:
        app.logger.warning("schema 迁移启动步骤跳过: %s", e)


def create_app(config_name: str | None = None):
    """应用工厂

    Args:
        config_name: 显式指定配置类(development/production/testing),
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

    if config_name:
        from config import config_map

        app.config.from_object(config_map.get(config_name, config_map["default"]))
    else:
        app.config.from_object(get_config())

    # 转为 timedelta 形式，默认 24 小时
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
        seconds=int(app.config.get("PERMANENT_SESSION_LIFETIME", 60 * 60 * 24))
    )

    app.wsgi_app = ProxyFix(  # type: ignore[method-assign]
        app.wsgi_app,
        x_for=app.config.get("PROXY_FIX_X_FOR", 0),
        x_proto=app.config.get("PROXY_FIX_X_PROTO", 0),
        x_host=app.config.get("PROXY_FIX_X_HOST", 0),
    )

    configure_pillow(app.config.get("PIL_MAX_IMAGE_PIXELS", 50_000_000))

    db.init_app(app)
    try:
        from flask_migrate import Migrate

        Migrate(app, db, directory=os.path.join(root_dir, "migrations"))
    except ImportError:
        log.warning("Flask-Migrate 未安装,跳过迁移支持")

    login_manager.init_app(app)
    csrf.init_app(app)
    babel.init_app(app, locale_selector=_select_locale)

    # CSRFProtect 只校验 POST/PUT/DELETE/PATCH，GET 静态文件与 favicon 不受影响
    _setup_logging(app)

    with app.app_context():
        from app.database import (
            ensure_admin_exists,
            ensure_default_settings,
            init_db,
            wait_for_database,
        )
        from app.utils import migrate_legacy_upload_dirs

        # 慢 SQL 探针，阈值 BLOG_SLOW_QUERY_MS
        register_slow_sql(db.engine, int(app.config.get("SLOW_QUERY_MS", 200)))

        wait_for_database()

        # 旧上传目录迁移（幂等）：static/banner -> uploads/banner，static/uploads -> uploads/image
        try:
            for msg in migrate_legacy_upload_dirs():
                app.logger.info(msg)
        except OSError:
            app.logger.warning("旧上传目录迁移失败", exc_info=True)

        # 各步骤相互独立，单步失败不影响其余步骤
        for _init_step in (init_db, ensure_default_settings, ensure_admin_exists):
            try:
                _init_step()
            except Exception as e:
                app.logger.warning("%s 跳过: %s", _init_step.__name__, e)

        run_startup_schema_migrations(app)

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

    def _safe_error_page(code: int, message: str):
        """渲染错误页；模板渲染失败时退回纯 HTML，避免二次抛错。"""
        try:
            return render_template("error.html", code=code, message=message), code
        except Exception:
            return f"<h1>{code}</h1><p>{message}</p>", code

    @app.errorhandler(HTTPException)
    def http_error_handler(e):
        # 按原始状态码返回，不统一归为 500
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

    @app.before_request
    def _assign_request_id():
        begin_request_id()

    @app.after_request
    def _echo_request_id(response):
        # 钩子短路的请求也回传，便于按 ID 查日志
        rid = getattr(g, "_request_id", None)
        if rid:
            response.headers[REQUEST_ID_HEADER] = rid
        return response

    @app.teardown_request
    def _reset_request_id(exc):
        end_request_id()

    @app.before_request
    def _validate_host():
        # 静态文件与健康探针放行，其余非白名单 Host 返回 400
        if request.endpoint in ("static", "main.healthz"):
            return None
        if not _is_trusted_host(request.host):
            app.logger.warning("拒绝非白名单 Host 请求: %s (ip=%s)", request.host, request.remote_addr)
            return jsonify({"error": "Invalid Host header"}), 400

    # 维护闸门：待迁移期间将业务请求导流到 503 升级页，放行登录 / 迁移 / 静态资源 / 健康探针
    @app.before_request
    def _schema_upgrade_gate():
        if not app.config.get("SCHEMA_UPGRADE_PENDING"):
            return None
        if request.endpoint in (
            "static",
            "main.healthz",
            "main.uploaded_file",
            "admin.login",
            "admin.logout",
            "admin.migrate_db",
        ):
            return None
        try:
            from app.database import (
                SCHEMA_VERSION,
                get_schema_version,
                pending_schema_migrations,
            )

            pending = pending_schema_migrations(quiet=True)
            if not pending:
                app.config["SCHEMA_UPGRADE_PENDING"] = False
                app.logger.info("数据库 schema 迁移已完成,维护模式自动解除")
                return None
            return (
                render_template(
                    "admin/upgrade_required.html",
                    db_version=get_schema_version() or "",
                    target_version=SCHEMA_VERSION,
                    pending=pending,
                ),
                503,
            )
        except Exception:
            return None

    @app.before_request
    def _start_request_timer():
        g._req_start = time.perf_counter()

    @app.after_request
    def _access_log(response):
        # 静态资源与健康探针不记访问日志
        if request.endpoint in ("static", "main.healthz", "main.uploaded_file"):
            return response
        duration_ms = int((time.perf_counter() - getattr(g, "_req_start", time.perf_counter())) * 1000)
        query = request.query_string.decode("utf-8", errors="replace")[:500] or None
        fields = {
            "method": request.method,
            "path": request.path,
            "query": query,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "ip": request.remote_addr,
            "user_id": getattr(current_user, "id", None),
            "user_agent": str(request.user_agent)[:300] or None,
        }
        # 5xx 记 ERROR；4xx 或超过慢请求阈值记 WARNING；其余 INFO
        if response.status_code >= 500:
            level = logging.ERROR
        elif response.status_code >= 400 or duration_ms >= int(app.config.get("SLOW_REQUEST_MS", 500)):
            level = logging.WARNING
        else:
            level = logging.INFO
        log_event(app.logger, level, "http_request", **fields)
        return response

    # 防盗链：放行空 Referer、同源与白名单站点引用，其余返回 403
    @app.before_request
    def _protect_hotlink():
        prefixes = app.config.get("HOTLINK_PROTECTED_PREFIXES") or ()
        if request.method not in ("GET", "HEAD") or not request.path.startswith(prefixes):
            return None
        referer = request.referrer
        if not referer:
            return None
        try:
            ref_host = urlsplit(referer).netloc
        except ValueError:
            return None
        if not ref_host:
            return None
        # 放行同源（忽略端口）与 Host 白名单站点
        allowed = {request.host.lower().split(":", 1)[0]}
        allowed |= {h.split(":", 1)[0] for h in (app.config.get("HOST_WHITELIST") or [])}
        if ref_host.lower().split(":", 1)[0] in allowed:
            return None
        app.logger.warning("拒绝外站盗链: %s -> %s (ip=%s)", referer, request.path, request.remote_addr)
        return jsonify({"error": "Hotlink denied"}), 403

    @app.after_request
    def _security_headers(response):
        response.headers["Content-Security-Policy"] = app.config.get("CSP_POLICY", "")
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # 仅 HTTPS 下下发 HSTS
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # 静态资源缓存策略；max-age 为 0 时不下发缓存头
        if request.endpoint in ("static", "main.uploaded_file") and response.status_code == 200:
            max_age = int(app.config.get("SEND_FILE_MAX_AGE_DEFAULT") or 0)
            if max_age > 0:
                response.headers["Cache-Control"] = f"public, max-age={max_age}, immutable"
        return response

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

    register_cli(app)

    return app


def register_cli(app: Flask):
    """注册 flask 命令:init-db / create-admin"""
    import click
    from flask.cli import with_appcontext

    @app.cli.command("init-db")
    @with_appcontext
    def init_db_cmd():
        """创建所有数据库表(幂等)"""
        from app.database import (
            ensure_admin_exists,
            ensure_default_settings,
            init_db,
            run_schema_migrations,
        )

        init_db()
        run_schema_migrations()
        ensure_default_settings()
        ensure_admin_exists()
        click.echo("Initialized database, applied schema migrations and ensured admin/settings tables.")

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
