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
    """校验请求 Host 是否在白名单内（BLOG_TRUSTED_HOSTS）。

    白名单为空时放行（仅开发便捷）；生产环境应配置真实域名。
    去除端口后再比对，支持 IPv6（带方括号）。
    """
    if not host:
        return False
    # 去除端口（兼容 IPv6 的 [::1]:5000 形式）
    host_only = host.split("]", 1)[0] + "]" if host.startswith("[") else host.split(":", 1)[0]
    trusted = current_app.config.get("HOST_WHITELIST") or []
    if not trusted:
        return True  # 未配置白名单时放行
    return host_only.lower() in trusted


def _setup_logging(app: Flask):
    """统一日志：控制台 + 按大小轮转的文件日志（LOG_DIR/app.log）。

    无论 python run.py / waitress / gunicorn / uWSGI 启动，应用日志
    （启动初始化、告警、未捕获异常、请求访问记录）都同时写控制台和文件，
    脱离启动终端也能回溯。gunicorn 多 worker 以 O_APPEND 共享同一文件，
    单条日志不会交错损坏。文件句柄幂等挂载，测试中反复 create_app()
    或 reloader 双进程不会产生重复行。

    日志级别（LOG_LEVEL，来自 BLOG_LOG_LEVEL）：
    - auto（默认）跟随 DEBUG 开关：debug 时 DEBUG、否则 INFO；
    - 显式 DEBUG / INFO / WARNING / ERROR / CRITICAL 则独立于 DEBUG 开关，
      例：生产排查问题可临时 BLOG_LOG_LEVEL=DEBUG（只多记日志，
      错误页仍由 DEBUG 开关决定是否外显堆栈）。
    """
    # 级别解析：显式值非法不阻断启动，回退 INFO 并在 handler 挂好后告警
    raw_level = str(app.config.get("LOG_LEVEL") or "auto").upper()
    bad_level = None
    if raw_level in ("", "AUTO"):
        level = logging.DEBUG if app.debug else logging.INFO
    else:
        # 临时变量承接 getattr 的 Any|None，经 isinstance 收窄后再赋给 level
        parsed = getattr(logging, raw_level, None)
        if not isinstance(parsed, int):
            bad_level = raw_level
            parsed = logging.INFO
        level = parsed
    # 结构化日志：生产默认单行 JSON（ELK/Loki 直接解析），开发/测试可读文本；
    # BLOG_LOG_FORMAT=json|text 可强制覆盖。控制台与文件使用同一 formatter。
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
        # 目录不可写（只读文件系统等）不阻断启动，退回仅控制台
        app.logger.warning("日志目录不可用,文件日志已禁用: %s", log_dir, exc_info=True)

    def _configure(target: logging.Logger):
        # Flask 首次访问 app.logger 时会自动挂一个 stderr 默认 handler，
        # 移除它（含测试中二次 create_app 同名 logger 的残留），由下面
        # 统一的控制台/文件 handler 取代，避免每条日志输出两份。
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
        # 此时 handler 已挂好，告警不会丢；不阻断启动
        app.logger.warning(
            "BLOG_LOG_LEVEL 取值非法(%s)，已回退 INFO；可用值：AUTO/DEBUG/INFO/WARNING/ERROR/CRITICAL",
            bad_level,
        )


def _select_locale():
    """Babel 选 locale：优先 session['lang'],其次 Accept-Language,最后默认"""
    lang = session.get("lang")
    if lang in ("zh_CN", "en"):
        return lang
    # 浏览器偏好
    best = request.accept_languages.best_match(["zh_CN", "en"])
    return best or "zh_CN"


babel = Babel()


def run_startup_schema_migrations(app) -> None:
    """启动时的 schema 迁移步骤,由 BLOG_AUTO_MIGRATE 决定模式。

    - true（默认）:程序版本 > 数据库版本时立即自动执行（与后台「迁移数据库」
      同一入口 run_schema_migrations）;
    - false:检测到待迁移项时**不动库**,只置维护闸门标志
      （app.config["SCHEMA_UPGRADE_PENDING"]）——由 create_app 注册的
      _schema_upgrade_gate 把全站请求导流到升级维护页,管理员登录后在
      「迁移数据库」页手动执行,完成后闸门自动解除。

    任何异常（含多 worker 抢迁移锁超时）只记 warning 不阻断启动:
    库可能暂时不可达,启动流程不该因此整体失败。
    """
    from app.database import pending_schema_migrations, run_schema_migrations

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

    # timedelta 形式的 PERMANENT_SESSION_LIFETIME（默认 24 小时）
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
        seconds=int(app.config.get("PERMANENT_SESSION_LIFETIME", 60 * 60 * 24))
    )

    # ── ProxyFix（信任反向代理头） ──────────────────────
    # 运行时替换 wsgi_app 是 Werkzeug 官方推荐的 ProxyFix 用法，故豁免 method-assign
    app.wsgi_app = ProxyFix(  # type: ignore[method-assign]
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
        from app.database import (
            ensure_admin_exists,
            ensure_default_settings,
            init_db,
            wait_for_database,
        )
        from app.utils import migrate_legacy_upload_dirs

        # 慢 SQL 探针（幂等挂到当前引擎；阈值 BLOG_SLOW_QUERY_MS，默认 200ms）
        register_slow_sql(db.engine, int(app.config.get("SLOW_QUERY_MS", 200)))

        # 先等数据库可连通（MySQL 容器首次初始化较慢）。超时直接抛出,
        # 由 gunicorn/容器重启策略重新拉起,避免初始化只跑一次却静默跳过。
        wait_for_database()

        # 旧上传目录迁移（幂等）：static/banner -> uploads/banner、
        # static/uploads -> uploads/image，保证升级实例的存量文件可用。
        try:
            for msg in migrate_legacy_upload_dirs():
                app.logger.info(msg)
        except OSError:
            app.logger.warning("旧上传目录迁移失败", exc_info=True)

        # 各步骤相互独立：多 worker 并发启动时,任一 worker 建表/写入失败
        # 不应导致其它初始化步骤被整体跳过。
        for _init_step in (init_db, ensure_default_settings, ensure_admin_exists):
            try:
                _init_step()
            except Exception as e:
                app.logger.warning("%s 跳过: %s", _init_step.__name__, e)

        # schema 迁移,由 BLOG_AUTO_MIGRATE 决定模式（自动执行 / 进入维护模式）。
        run_startup_schema_migrations(app)

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

    # ── 请求关联 ID（最先注册，保证后续 Host 校验/防盗链/访问日志都能带上） ──
    @app.before_request
    def _assign_request_id():
        begin_request_id()

    @app.after_request
    def _echo_request_id(response):
        # 即使后续钩子短路（如 Host 400）也回传，便于网关/客户端按 ID 查日志
        rid = getattr(g, "_request_id", None)
        if rid:
            response.headers[REQUEST_ID_HEADER] = rid
        return response

    @app.teardown_request
    def _reset_request_id(exc):
        end_request_id()

    # ── Host 白名单校验（防 Host 头注入 / 密码重置邮件投毒） ─
    @app.before_request
    def _validate_host():
        # 静态文件与容器健康探针放行（探针 Host 为容器内地址，无法预知）；
        # 其余非白名单 Host 返回 400。
        if request.endpoint in ("static", "main.healthz"):
            return None
        if not _is_trusted_host(request.host):
            app.logger.warning("拒绝非白名单 Host 请求: %s (ip=%s)", request.host, request.remote_addr)
            return jsonify({"error": "Invalid Host header"}), 400

    # ── 维护闸门：BLOG_AUTO_MIGRATE=false 且存在待迁移 schema 时启用 ─────
    # 业界做法(Nextcloud/WordPress 同款):待迁移期间站点全部导流到一个
    # 「零 schema 依赖」的升级页(503),只放行 登录/迁移/退出/静态资源/健康
    # 探针——登录链路只触碰 admin、login_attempt、rate_limit 三张跨版本
    # 稳定的表(**这三张表永不做 schema 变更**,登录是迁移的唯一入口),
    # 升级页不继承 base.html、不查任何业务表。
    # 自恢复:gate 每请求重查 pending,迁移一旦被任何入口完成(本进程手动
    # POST 后已清标志;另一 worker/CLI 完成时靠这里)即自动放行,无需重启。
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
            # DB 读失败不做武断拦截,交给各层既有的异常兜底处理
            return None

    # ── 请求计时 + 结构化访问日志（waitress/gunicorn 下无 werkzeug 访问日志，
    #    由应用层统一记录每个业务请求；静态资源/健康探针跳过避免刷屏） ──
    @app.before_request
    def _start_request_timer():
        g._req_start = time.perf_counter()

    @app.after_request
    def _access_log(response):
        # 静态/上传文件与健康探针不记访问日志，避免页面图片请求刷屏
        if request.endpoint in ("static", "main.healthz", "main.uploaded_file"):
            return response
        duration_ms = int((time.perf_counter() - getattr(g, "_req_start", time.perf_counter())) * 1000)
        # 查询串单独成字段（截断防超长），路径保持纯净便于聚合
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
        # 5xx ERROR；4xx 或超过慢请求阈值 WARNING；其余 INFO
        if response.status_code >= 500:
            level = logging.ERROR
        elif response.status_code >= 400 or duration_ms >= int(app.config.get("SLOW_REQUEST_MS", 500)):
            level = logging.WARNING
        else:
            level = logging.INFO
        log_event(app.logger, level, "http_request", **fields)
        return response

    # ── 上传资源防盗链（对齐原 nginx valid_referers，迁移至应用层） ──
    # 轮播图/文章上传图仅允许：空 Referer、同源请求、Host 白名单站点引用；
    # 其余 Referer 返回 403。
    @app.before_request
    def _protect_hotlink():
        prefixes = app.config.get("HOTLINK_PROTECTED_PREFIXES") or ()
        if request.method not in ("GET", "HEAD") or not request.path.startswith(prefixes):
            return None
        referer = request.referrer
        if not referer:
            return None  # 空 Referer 放行（对齐 valid_referers none）
        try:
            ref_host = urlsplit(referer).netloc
        except ValueError:
            return None
        if not ref_host:
            return None  # 无法解析的 Referer 放行（对齐 valid_referers blocked）
        # 同源（忽略端口）或 Host 白名单内的站点放行；
        # 白名单为空时仅同源放行（防盗链不因白名单未配置而失效）
        allowed = {request.host.lower().split(":", 1)[0]}
        allowed |= {h.split(":", 1)[0] for h in (app.config.get("HOST_WHITELIST") or [])}
        if ref_host.lower().split(":", 1)[0] in allowed:
            return None
        app.logger.warning("拒绝外站盗链: %s -> %s (ip=%s)", referer, request.path, request.remote_addr)
        return jsonify({"error": "Hotlink denied"}), 403

    # ── 安全响应头（应用层统一下发，nginx 只做纯转发） ────
    # 单一事实来源：无论直连、nginx 还是 Docker 部署，防护始终一致，
    # 且随代码进版本库、有测试覆盖。⚠️ 不要在 nginx 再 add_header 重复下发
    # CSP（浏览器对多份 CSP 取交集执行，极易出现莫名拦资源）。
    @app.after_request
    def _security_headers(response):
        response.headers["Content-Security-Policy"] = app.config.get("CSP_POLICY", "")
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # HSTS 仅在 HTTPS 下下发；经 nginx 终结 TLS 时依赖 ProxyFix(x_proto)
        # 还原真实协议（BLOG_PROXY_XPROTO=1）
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # 静态/上传资源缓存策略（对齐原 nginx expires 30d + immutable）；
        # BLOG_STATIC_MAX_AGE=0（开发默认）时不加缓存头，避免调试看到旧资源
        if request.endpoint in ("static", "main.uploaded_file") and response.status_code == 200:
            max_age = int(app.config.get("SEND_FILE_MAX_AGE_DEFAULT") or 0)
            if max_age > 0:
                response.headers["Cache-Control"] = f"public, max-age={max_age}, immutable"
        return response

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
