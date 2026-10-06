"""结构化日志 / request_id / 慢请求 / 慢 SQL 探针测试。"""

import json
import logging

import pytest

from app.observability import (
    JsonFormatter,
    RequestIdFilter,
    TextFormatter,
    build_formatter,
)


class _CaptureHandler(logging.Handler):
    """收集日志记录（formatter 之前的原始 record，便于断言结构化字段）。"""

    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture()
def capture():
    """挂到 blog / app 两个 logger 上捕获请求期间产生的全部记录。"""
    h = _CaptureHandler()
    h.addFilter(RequestIdFilter())  # 与生产 handler 一致，为记录注入 request_id
    loggers = [logging.getLogger("blog"), logging.getLogger("app"), logging.getLogger("blog.slowsql")]
    for lg in loggers:
        lg.addHandler(h)
    yield h
    for lg in loggers:
        lg.removeHandler(h)


# ── Formatter ─────────────────────────────────────────────
def _make_record(**fields):
    return logging.LogRecord(
        name="app",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="http_request",
        args=(),
        exc_info=None,
    )


def test_json_formatter_outputs_parseable_fields():
    rec = _make_record()
    # 直接构造带 log_fields 的记录
    rec.log_fields = {"path": "/", "status_code": 200, "duration_ms": 12}
    rec.request_id = "abc123"
    out = json.loads(JsonFormatter().format(rec))
    assert out["msg"] == "http_request"
    assert out["request_id"] == "abc123"
    assert out["path"] == "/"
    assert out["status_code"] == 200
    assert out["duration_ms"] == 12
    assert out["level"] == "INFO"
    assert "ts" in out


def test_json_formatter_includes_exc_info():
    try:
        raise ValueError("boom")
    except ValueError:
        rec = logging.LogRecord("app", logging.ERROR, __file__, 1, "fail", (), __import__("sys").exc_info())
    out = json.loads(JsonFormatter().format(rec))
    assert out["msg"] == "fail"
    assert "ValueError: boom" in out["exc_info"]


def test_text_formatter_readable_and_idempotent():
    rec = _make_record()
    rec.log_fields = {"path": "/x", "status_code": 404}
    rec.request_id = "rid-1"
    f = TextFormatter()
    first = f.format(rec)
    second = f.format(rec)  # 同一条记录经两个 handler，后缀不得叠加
    assert first == second
    assert "[rid-1]" in first
    assert "http_request path=/x status_code=404" in first


def test_build_formatter_auto_selection():
    assert isinstance(build_formatter("auto", debug=False, testing=False), JsonFormatter)
    assert isinstance(build_formatter("auto", debug=True, testing=False), TextFormatter)
    assert isinstance(build_formatter("auto", debug=False, testing=True), TextFormatter)
    assert isinstance(build_formatter("text", debug=False, testing=False), TextFormatter)
    assert isinstance(build_formatter("json", debug=True, testing=True), JsonFormatter)


# ── request_id ────────────────────────────────────────────
def test_request_id_echoed_from_header(client):
    rv = client.get("/", headers={"X-Request-ID": "trace-abc-123-456"})
    assert rv.headers["X-Request-ID"] == "trace-abc-123-456"


def test_request_id_generated_when_absent(client):
    rv = client.get("/")
    rid = rv.headers["X-Request-ID"]
    assert len(rid) == 32  # uuid4 hex
    int(rid, 16)  # 纯十六进制


@pytest.mark.parametrize("bad", ["", "a", "has space", "<script>", "x" * 65, "bad/char"])
def test_request_id_invalid_header_replaced(client, bad):
    rv = client.get("/", headers={"X-Request-ID": bad})
    rid = rv.headers["X-Request-ID"]
    assert rid != bad
    assert len(rid) == 32


def test_request_id_propagates_into_log_records(client, capture):
    rv = client.get("/no-such-page-xyz")  # 404 -> WARNING http_request
    rid = rv.headers["X-Request-ID"]
    access = [r for r in capture.records if r.getMessage() == "http_request"]
    assert len(access) == 1
    rec = access[0]
    assert rec.levelno == logging.WARNING
    assert rec.request_id == rid
    fields = rec.log_fields
    assert fields["path"] == "/no-such-page-xyz"
    assert fields["status_code"] == 404
    assert isinstance(fields["duration_ms"], int)
    assert fields["method"] == "GET"


def test_request_id_reset_after_request(client):
    from app.observability import request_id_var

    client.get("/")
    assert request_id_var.get() is None  # contextvar 已复位，不串请求


# ── 慢请求 ────────────────────────────────────────────────
def test_slow_request_escalates_to_warning(app, client, capture):
    app.config["SLOW_REQUEST_MS"] = 0  # 所有请求都超阈值
    rv = client.get("/")
    assert rv.status_code == 200
    rec = next(r for r in capture.records if r.getMessage() == "http_request")
    assert rec.levelno == logging.WARNING
    assert rec.log_fields["duration_ms"] >= 0


def test_fast_request_stays_info(app, client, capture):
    app.config["SLOW_REQUEST_MS"] = 600000  # 10 分钟，不可能触发
    client.get("/")
    rec = next(r for r in capture.records if r.getMessage() == "http_request")
    assert rec.levelno == logging.INFO


# ── 慢 SQL ────────────────────────────────────────────────
def test_slow_sql_emitted_when_threshold_zero(capture):
    """阈值 0ms：任意 SQL 都产生 slow_query 事件，且带 request_id。"""
    from app import create_app
    from app.extensions import db as _db
    from app.observability import register_slow_sql

    app2 = create_app("testing")
    # 直接在该 app 的引擎上以 0 阈值挂探针（config 值在模块导入时固化，
    # 用例聚焦验证探针机制本身；生产阈值由 BLOG_SLOW_QUERY_MS 决定）
    with app2.app_context():
        engine = _db.engine
        engine._blog_slow_sql_registered = False
        register_slow_sql(engine, 0)
    client2 = app2.test_client()
    # 捕获挂在全局 logger 上，新建 app 产生的慢 SQL 也会冒泡上来
    client2.get("/", headers={"X-Request-ID": "slow-sql-rid"})
    slow = [r for r in capture.records if r.getMessage() == "slow_query"]
    assert slow, "首页至少有一次查询，阈值为 0 时应记录 slow_query"
    rec = slow[0]
    assert rec.levelno == logging.WARNING
    assert rec.log_fields["duration_ms"] >= 0
    assert "select" in rec.log_fields["statement"].lower()
    assert len(rec.log_fields["statement"]) <= 500
    assert rec.request_id == "slow-sql-rid"


def test_slow_sql_silent_with_high_threshold(app, client, capture):
    """阈值很高时普通查询不应产生 slow_query 噪声。

    app fixture 的引擎用默认阈值 200ms 创建；内存 SQLite 查询远低于此。
    """
    client.get("/")
    assert not [r for r in capture.records if r.getMessage() == "slow_query"]
