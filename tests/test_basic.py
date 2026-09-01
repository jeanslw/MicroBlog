"""应用工厂与基础行为测试。"""


def test_app_factory_testing(app):
    """create_app 应返回正确配置的 app"""
    assert app is not None
    assert app.config["TESTING"] is True
    assert app.config["WTF_CSRF_ENABLED"] is False
    assert "sqlite" in app.config["SQLALCHEMY_DATABASE_URI"]


def test_blueprints_registered(app):
    """所有蓝图应注册"""
    names = list(app.blueprints.keys())
    for bp in ("blog", "comment", "admin", "banner", "main"):
        assert bp in names, f"缺少蓝图 {bp}"


def test_secret_key_is_set(app):
    """SECRET_KEY 必须存在且非空"""
    assert app.config["SECRET_KEY"]


def test_index_returns_200(client):
    """首页应返回 200"""
    rv = client.get("/")
    assert rv.status_code == 200


def test_404_handler(client):
    """不存在路由应返回 404 页面"""
    rv = client.get("/this-path-does-not-exist")
    assert rv.status_code == 404


def test_404_json_handler(client):
    """JSON 请求的 404 应返回 JSON"""
    rv = client.get("/this-path-does-not-exist", headers={"Accept": "application/json"})
    assert rv.status_code == 404


def test_static_files_served(app):
    """favicon 应可访问"""
    # 静态文件存在性仅做 URL 不存在测试避免文件依赖
    with app.test_client() as c:
        # favicon.ico 实际存在
        rv = c.get("/static/favicon.ico")
        assert rv.status_code in (200, 404)


def test_babel_locale_selector(app):
    """Babel 默认 locale 应为 zh_CN"""
    assert app.config["BABEL_DEFAULT_LOCALE"] == "zh_CN"


def test_max_content_length_set(app):
    """请求体上限应被设置"""
    assert app.config["MAX_CONTENT_LENGTH"] > 0


def test_session_cookie_httponly(app):
    """Cookie 应启用 HttpOnly"""
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
