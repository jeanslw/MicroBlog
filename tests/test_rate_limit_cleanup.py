"""限流记录惰性清理的回归（P1）。

旧实现把「清理窗口外旧记录」与「插入本次计数」放在同一个事务里，超限时用
``rollback()`` 表示「本次不计数」—— 结果把清理一起回滚了：越是被限流的
IP/动作，过期记录越清不掉，``rate_limit`` 表只增不减（且每次请求的清理 SQL
都要全表扫描）。现在清理先单独提交，判定后仅提交本次插入。
"""

from datetime import datetime, timedelta

from app.extensions import check_and_record_rate_limit
from app.models import RateLimit


def _stamp(minutes_ago: int = 0) -> str:
    return (datetime.now() - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")


def test_expired_rows_are_cleaned_even_when_request_is_rejected(app, db):
    now = _stamp()
    db.session.add(RateLimit(ip="1.2.3.4", action="comment", create_time=_stamp(30)))  # 窗口外
    db.session.add(RateLimit(ip="1.2.3.4", action="comment", create_time=now))  # 窗口内
    db.session.commit()

    allowed = check_and_record_rate_limit("comment", "1.2.3.4", limit=1, window_seconds=300)

    assert allowed is False, "窗口内已有 1 条记录，应判定超限"
    rows = db.session.scalars(db.select(RateLimit)).all()
    assert len(rows) == 1, "被拒绝的请求也必须清掉窗口外的过期记录"
    assert rows[0].create_time == now


def test_records_stop_growing_once_limit_reached(app, db):
    assert check_and_record_rate_limit("vote", "9.9.9.9", limit=2, window_seconds=300) is True
    assert check_and_record_rate_limit("vote", "9.9.9.9", limit=2, window_seconds=300) is True
    assert check_and_record_rate_limit("vote", "9.9.9.9", limit=2, window_seconds=300) is False

    assert db.session.scalar(db.select(db.func.count(RateLimit.id))) == 2


def test_window_expiry_allows_new_requests(app, db):
    """窗口滑出后应重新放行（阈值按当前时间重算）。"""
    db.session.add(RateLimit(ip="8.8.8.8", action="reply", create_time=_stamp(10)))
    db.session.commit()

    assert check_and_record_rate_limit("reply", "8.8.8.8", limit=1, window_seconds=300) is True
