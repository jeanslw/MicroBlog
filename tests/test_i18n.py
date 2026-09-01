"""国际化与通用路由测试。"""


def test_default_locale_zh_cn(client):
    """默认语言为中文"""
    rv = client.get("/")
    assert rv.status_code == 200
    # 中文标记
    assert "首页".encode() in rv.data


def test_set_lang_en(client):
    """切换到英文后页面应展示英文"""
    client.get("/set_lang/en", follow_redirects=True)
    rv = client.get("/")
    assert rv.status_code == 200
    assert b"Home" in rv.data


def test_set_lang_zh_cn(client):
    """切换回中文应展示中文"""
    client.get("/set_lang/en")
    client.get("/set_lang/zh_CN")
    rv = client.get("/")
    assert "首页".encode() in rv.data


def test_set_lang_invalid_ignored(client):
    """非法语言代码应被忽略（不改变当前 locale）"""
    client.get("/set_lang/fr")
    rv = client.get("/")
    assert rv.status_code == 200
    # 默认 zh_CN
    assert "首页".encode() in rv.data


def test_set_lang_redirects_back(client):
    """切换语言应重定向回原页面"""
    rv = client.get("/set_lang/en", follow_redirects=False)
    assert rv.status_code == 302


def test_accept_language_header_en(client):
    """Accept-Language: en 应使用英文"""
    rv = client.get("/", headers={"Accept-Language": "en"})
    assert rv.status_code == 200
    assert b"Home" in rv.data


def test_accept_language_header_zh(client):
    """Accept-Language: zh 应使用中文"""
    rv = client.get("/", headers={"Accept-Language": "zh-CN,zh;q=0.9"})
    assert rv.status_code == 200
    assert "首页".encode() in rv.data


def test_robots_txt(client):
    """robots.txt 应可访问"""
    rv = client.get("/robots.txt")
    assert rv.status_code == 200
    assert b"User-agent" in rv.data
    assert b"Allow" in rv.data
    assert rv.mimetype == "text/plain"


def test_lang_switch_link_present(client):
    """页面应包含语言切换链接"""
    rv = client.get("/")
    assert b"/set_lang/" in rv.data


def test_english_translation_loaded(app):
    """英文 .mo 翻译应已加载并工作"""
    with app.test_request_context("/", headers={"Accept-Language": "en"}):
        from flask_babel import _

        assert _("首页") == "Home"
        assert _("登录") == "Log In"


def test_chinese_translation_loaded(app):
    """中文 .mo 翻译应已加载并工作"""
    with app.test_request_context("/", headers={"Accept-Language": "zh-CN"}):
        from flask_babel import _

        assert _("首页") == "首页"
