"""密码重置令牌的安全约束(P1).

重置链接以 URL path 段传输，而 URLSafeTimedSerializer 只签名不加密，
payload 是明文 base64。因此令牌里不能携带密码哈希全文，否则哈希会落进
访问日志、浏览器历史与 Referer。

令牌只绑一个自增版本号(token_version):此类 seriousness 的约束不该依赖
对密文做任何哈希——那会被静态检查判为"对口令类数据使用弱哈希"。改密码时
版本号 +1,此前签发的令牌自然失效,语义与摘要方案等价。
"""

import base64


def _decode_payload(token: str) -> str:
    """还原 itsdangerous 令牌的明文 payload（仅签名，不加密）。"""
    part = token.split(".")[0]
    part += "=" * (-len(part) % 4)
    return base64.urlsafe_b64decode(part).decode("utf-8", "replace")


def test_reset_token_does_not_carry_password_hash(app, admin_user):
    """令牌内不应出现密码哈希原文，也不应出现任何由密码派生的字段"""
    from app.admin.routes import _make_reset_token

    token = _make_reset_token(admin_user)
    payload = _decode_payload(token)

    assert admin_user.password, "前提：管理员密码哈希非空"
    assert admin_user.password not in token
    assert admin_user.password not in payload
    assert "scrypt" not in payload
    assert "pbkdf2" not in payload
    assert "pwh" not in payload, "令牌不得再携带密码哈希摘要"


def _forget_cached_user():
    """丢弃 Flask-Login 缓存的当前用户。

    Flask-Login 把解析后的用户挂在 app 上下文的 g 上(_get_user 见缓存即不再
    读 session),而测试 fixture 的 app context 被同一用例内的所有请求复用。
    登录过的 client 与匿名 client 会共用这份缓存,故切换身份前必须清掉。
    """
    from flask import g

    g.pop("_login_user", None)


def test_reset_token_invalid_after_password_change(app, login_admin, admin_user):
    """改密码后旧令牌应失效——走真实改密路由，而非手工改 password 字段"""
    from app.admin.routes import _make_reset_token

    # 重置页只接受匿名访问,而 login_admin 已把本用例的身份登录到位
    anon = app.test_client()
    _forget_cached_user()
    token = _make_reset_token(admin_user)
    rv = anon.get(f"/admin/reset/{token}", follow_redirects=False)
    assert rv.status_code == 200, "密码未变时令牌应可用"

    # 匿名 GET 之后缓存又被填成匿名用户,改密前需再次清空让后台路由重新识别登录态
    _forget_cached_user()

    rv = login_admin.post(
        "/admin/change_pwd",
        data={
            "old_pwd": "admin123456",
            "new_pwd": "brand-new-123",
            "confirm_pwd": "brand-new-123",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302, "改密应成功并跳转登录页"
    assert admin_user.token_version == 1, "改密必须自增 token_version"

    # change_pwd 退出登录后,缓存里仍是刚登录的那位(见 _forget_cached_user 说明)
    _forget_cached_user()

    rv = anon.get(f"/admin/reset/{token}", follow_redirects=False)
    assert rv.status_code == 302, "密码变更后旧令牌应失效"


def test_reset_consumes_token(client, admin_user):
    """重置成功后同一条链接不能再用第二次"""
    from app.admin.routes import _make_reset_token

    token = _make_reset_token(admin_user)
    rv = client.post(
        f"/admin/reset/{token}",
        data={"new_pwd": "resetted-pwd-1", "confirm_pwd": "resetted-pwd-1"},
        follow_redirects=False,
    )
    assert rv.status_code == 302, "重置应成功并跳转登录页"

    rv = client.get(f"/admin/reset/{token}", follow_redirects=False)
    assert rv.status_code == 302, "重置成功后链接应已作废"
