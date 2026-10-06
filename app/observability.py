"""可观测性组件（零第三方依赖）。

- 结构化日志：``JsonFormatter`` 输出单行 JSON（ELK/Loki 直接解析），
  ``TextFormatter`` 输出本地可读格式；两者共用同一套字段与 request_id。
- 请求关联 ID：``X-Request-ID`` 传入则沿用（便于网关/上游串联），否则生成
  uuid4 hex；同一次请求内所有日志（含慢 SQL）自动带上，响应头回传。
- 手动性能埋点：请求耗时超过阈值记 WARNING（事件 ``http_request``），
  SQL 执行超过阈值记 WARNING（事件 ``slow_query``），无需 APM 后端即可
  在日志聚合系统中按 duration_ms / path / statement 聚合。

字段约定（日志聚合时按这些 key 建索引）：
    ts / level / logger / request_id / msg / event
    method / path / status_code / duration_ms / ip / user_id / user_agent
    statement（慢 SQL，已折叠空白并截断）
"""

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar

from flask import g, request
from sqlalchemy import event

# ── 请求关联 ID ────────────────────────────────────────────
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

REQUEST_ID_HEADER = "X-Request-ID"
# 仅接受网关/客户端传入的受控字符（防日志注入：不允许换行/空格/尖括号等）
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")

_SQL_START_ATTR = "_blog_sql_start"
_SQL_MAX_LEN = 500  # 慢 SQL 语句截断长度，避免超长 IN 列表刷屏


def get_request_id() -> str | None:
    """获取当前上下文的 request_id（请求外为 None）。"""
    return request_id_var.get()


def begin_request_id() -> str:
    """请求开始：解析/生成 request_id 并写入 contextvar。

    合法的上游 X-Request-ID 原样沿用；缺失或含非法字符时生成新 ID，
    防止伪造值向日志注入换行/伪造字段（JSON 本身也会转义，双保险）。
    """
    candidate = (request.headers.get(REQUEST_ID_HEADER) or "").strip()
    rid = candidate if _REQUEST_ID_RE.match(candidate) else uuid.uuid4().hex
    g._request_id = rid
    g._request_id_token = request_id_var.set(rid)
    return rid


def end_request_id() -> None:
    """请求结束：复位 contextvar。

    Flask 的 teardown 在异常路径/测试上下文下可能对同一请求执行多次，
    token 只能 reset 一次，用 g 上的标志保证幂等。
    """
    token = getattr(g, "_request_id_token", None)
    if token is not None:
        g._request_id_token = None
        request_id_var.reset(token)


class RequestIdFilter(logging.Filter):
    """给每条日志记录补 request_id 字段（无请求上下文时为 "-"）。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = request_id_var.get() or "-"
        return True


# ── 结构化字段传递 ─────────────────────────────────────────
def log_event(logger: logging.Logger, level: int, event: str, **fields) -> None:
    """发一条带结构化字段的日志。

    fields 通过 extra.log_fields 传递，由两种 Formatter 分别渲染为
    JSON 键值或文本 key=value 后缀；业务代码不要把字段拼进 msg。
    """
    logger.log(level, event, extra={"log_fields": fields})


class JsonFormatter(logging.Formatter):
    """单行 JSON 格式（供 ELK / Loki / CloudWatch 直接采集解析）。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "msg": record.getMessage(),
        }
        fields = getattr(record, "log_fields", None)
        if isinstance(fields, dict):
            payload.update({k: v for k, v in fields.items() if v is not None})
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # default=str：datetime/Decimal 等非常规类型兜底转字符串，不丢日志
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """本地可读格式：[time] LEVEL [request_id] in logger: msg key=val ..."""

    _FMT = "[%(asctime)s] %(levelname)s [%(request_id)s] in %(name)s: %(message)s"

    def __init__(self) -> None:
        super().__init__(self._FMT)

    def format(self, record: logging.LogRecord) -> str:
        if not getattr(record, "request_id", None):
            record.request_id = "-"
        fields = getattr(record, "log_fields", None)
        base = record.getMessage()
        if isinstance(fields, dict) and fields:
            suffix = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
            base = f"{base} {suffix}" if suffix else base
        # 临时替换 msg/args 调父类格式化，不修改原始 record
        # （同一条记录会依次经过控制台、文件两个 handler，避免后缀叠加两次）
        saved_msg, saved_args = record.msg, record.args
        record.msg, record.args = base, ()
        try:
            return super().format(record)
        finally:
            record.msg, record.args = saved_msg, saved_args


def build_formatter(log_format: str, *, debug: bool, testing: bool) -> logging.Formatter:
    """按配置构造 formatter；auto 时生产 JSON、开发/测试文本。"""
    fmt = (log_format or "auto").lower()
    if fmt == "auto":
        fmt = "text" if (debug or testing) else "json"
    if fmt == "json":
        return JsonFormatter()
    return TextFormatter()


# ── 慢 SQL 探针 ────────────────────────────────────────────
def register_slow_sql(engine, threshold_ms: int) -> None:
    """在 SQLAlchemy 引擎上挂执行耗时探针（幂等，每引擎只挂一次）。

    超过 threshold_ms 的语句以 WARNING 记录到 ``blog.slowsql`` logger
    （向上传播到应用统一 handler，天然带上 request_id）。只记语句不记参数：
    参数可能含登录口令等敏感值，且聚合分析按语句模板即可。
    """
    if getattr(engine, "_blog_slow_sql_registered", False):
        return
    engine._blog_slow_sql_registered = True
    slow_logger = logging.getLogger("blog.slowsql")

    @event.listens_for(engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        conn.info[_SQL_START_ATTR] = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        # 只读取不 pop：before 每次执行前都会覆盖，且允许多个监听器
        # （如测试/二次注册）共存而不会互相清掉计时键。
        start = conn.info.get(_SQL_START_ATTR)
        if start is None:
            return
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        if elapsed_ms >= threshold_ms:
            compact_sql = " ".join(statement.split())[:_SQL_MAX_LEN]
            log_event(
                slow_logger,
                logging.WARNING,
                "slow_query",
                duration_ms=elapsed_ms,
                statement=compact_sql,
            )
