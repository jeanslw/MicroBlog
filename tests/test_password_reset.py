"""密码重置令牌的安全约束(P1).

重置链接以 URL path 段传输，而 URLSafeTimedSerializer 只签名不加密，
payload 是明文 base64。因此令牌里不能携带密码哈希全文，否则哈希会落进
访问日志、浏览器历史与 Referer；改用短摘要后仍保留「改密即失效」的语义。
"""

import base64


def _decode_payload(token: str) -> str:
    """还原 itsdangerous 令牌的明文 payload（仅签名，不加密）。"""
    part = token.split(".")[0]
    part += "=" * (-len(part) % 4)
    return base64.urlsafe_b64decode(part).decode("utf-8", "replace")


def test_reset_token_does_not_carry_password_hash(app, admin_user):
    """令牌内不应出现密码哈希原文"""
    from app.admin.routes import _make_reset_token

    token = _make_reset_token(admin_user)
    payload = _decode_payload(token)

    assert admin_user.password, "前提：管理员密码哈希非空"
    assert admin_user.password not in token
    assert admin_user.password not in payload
    assert "scrypt" not in payload
    assert "pbkdf2" not in payload


def test_reset_token_invalid_after_password_change(app, db, admin_user, client):
    """改密码后旧令牌应失效——摘要方案必须保留此语义"""
    from app.admin.routes import _make_reset_token

    token = _make_reset_token(admin_user)
    rv = client.get(f"/admin/reset/{token}", follow_redirects=False)
    assert rv.status_code == 200, "密码未变时令牌应可用"

    admin_user.password = "another-hash-value"
    db.session.commit()

    rv = client.get(f"/admin/reset/{token}", follow_redirects=False)
    assert rv.status_code == 302, "密码变更后旧令牌应失效"
