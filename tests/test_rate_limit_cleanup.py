"""限流计数器的并发安全语义回归.

计数走数据库端条件更新,并发下放行数不超过阈值;过期窗口惰性清理;
数据库异常时默认放行,安全敏感动作可指定拒绝.
"""

from datetime import timedelta

from app.extensions import check_and_record_rate_limit
from app.models import RateLimitCounter
from app.timeutil import UTC_FORMAT, utc_now


def _stamp(minutes_ago: int = 0) -> str:
    return (utc_now() - timedelta(minutes=minutes_ago)).strftime(UTC_FORMAT)


def _boom(self):
    raise RuntimeError("db down")


def test_limit_enforced_across_calls(app, db):
    assert check_and_record_rate_limit("vote", "9.9.9.9", limit=2, window_seconds=300) is True
    assert check_and_record_rate_limit("vote", "9.9.9.9", limit=2, window_seconds=300) is True
    assert check_and_record_rate_limit("vote", "9.9.9.9", limit=2, window_seconds=300) is False
    assert check_and_record_rate_limit("vote", "9.9.9.9", limit=2, window_seconds=300) is False

    counter = db.session.scalar(db.select(RateLimitCounter).filter_by(action="vote", ip="9.9.9.9"))
    assert counter.count == 2, "超限请求不得继续累加计数"


def test_window_expiry_allows_new_requests(app, db):
    db.session.add(RateLimitCounter(ip="8.8.8.8", action="reply", window_start=_stamp(10), count=3))
    db.session.commit()

    assert check_and_record_rate_limit("reply", "8.8.8.8", limit=1, window_seconds=300) is True
    counter = db.session.scalar(db.select(RateLimitCounter).filter_by(action="reply", ip="8.8.8.8"))
    assert counter.count == 1, "窗口过期后计数应重置"


def test_expired_rows_are_cleaned_even_when_request_is_rejected(app, db):
    db.session.add(RateLimitCounter(ip="1.2.3.4", action="comment", window_start=_stamp(30), count=1))
    db.session.add(RateLimitCounter(ip="1.2.3.5", action="comment", window_start=_stamp(30), count=5))
    db.session.commit()

    allowed = check_and_record_rate_limit("comment", "1.2.3.4", limit=1, window_seconds=300)

    assert allowed is True, "窗口过期计数重置后应放行"
    rows = db.session.scalars(db.select(RateLimitCounter)).all()
    assert len(rows) == 1, "同动作的过期计数行应被惰性清理"
    assert rows[0].ip == "1.2.3.4"


def test_db_error_fail_open_by_default(app, db, monkeypatch):
    from sqlalchemy.orm import Session

    monkeypatch.setattr(Session, "commit", _boom)
    assert check_and_record_rate_limit("comment", "7.7.7.7", limit=1, window_seconds=300) is True


def test_db_error_fail_closed_when_requested(app, db, monkeypatch):
    from sqlalchemy.orm import Session

    monkeypatch.setattr(Session, "commit", _boom)
    assert check_and_record_rate_limit("forgot", "7.7.7.7", limit=1, window_seconds=300, fail_closed=True) is False


def test_concurrent_first_insert_race(app, db, monkeypatch):
    """并发首插冲突后应走条件更新重试,不吞掉放行机会"""
    from sqlalchemy import insert as sa_insert
    from sqlalchemy.orm import Session

    original_execute = Session.execute

    def racing_execute(self, statement, *args, **kwargs):
        table = getattr(statement, "table", None)
        if getattr(statement, "is_insert", False) and table is not None and table.name == "rate_limit_counter":
            with db.engine.begin() as conn:
                conn.execute(
                    sa_insert(RateLimitCounter).values(action="comment", ip="6.6.6.6", window_start=_stamp(0), count=1)
                )
        return original_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "execute", racing_execute)
    assert check_and_record_rate_limit("comment", "6.6.6.6", limit=5, window_seconds=300) is True
    counter = db.session.scalar(db.select(RateLimitCounter).filter_by(action="comment", ip="6.6.6.6"))
    assert counter.count == 2
