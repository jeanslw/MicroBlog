"""安全响应头 / 静态缓存 / 防盗链（应用层统一下发）测试。

安全头由 app/__init__.py 的 after_request 钩子下发（单一事实来源），
替代原 nginx add_header 配置；防盗链对齐原 nginx valid_referers 行为。
"""

EXISTING_STATIC = "/static/js/cursor-effect.js"


def _assert_security_headers(resp):
    assert resp.headers["Content-Security-Policy"] == (
        "default-src 'self'; img-src 'self' data: https:; media-src 'self' https:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; frame-ancestors 'self'"
    )
    assert resp.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


class TestSecurityHeaders:
    def test_homepage_has_security_headers(self, client):
        rv = client.get("/")
        assert rv.status_code == 200
        _assert_security_headers(rv)

    def test_csp_allows_external_media(self, client):
        """回归防护：缺失 media-src 会回退 default-src 'self'，
        导致文章插入的外链音视频无法播放。"""
        rv = client.get("/")
        csp = rv.headers["Content-Security-Policy"]
        assert "media-src 'self' https:" in csp
        assert "img-src 'self' data: https:" in csp

    def test_error_response_also_has_headers(self, client):
        """对齐 nginx add_header ... always：错误响应同样携带安全头。"""
        rv = client.get("/definitely-not-exist")
        assert rv.status_code == 404
        _assert_security_headers(rv)

    def test_static_file_has_headers(self, client):
        rv = client.get(EXISTING_STATIC)
        assert rv.status_code == 200
        _assert_security_headers(rv)

    def test_hsts_absent_on_http(self, client):
        rv = client.get("/")
        assert "Strict-Transport-Security" not in rv.headers

    def test_hsts_present_on_https(self, client):
        rv = client.get("/", base_url="https://localhost/")
        assert rv.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"


class TestStaticCacheControl:
    def test_no_cache_headers_when_max_age_zero(self, app, client):
        app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
        rv = client.get(EXISTING_STATIC)
        assert rv.status_code == 200
        assert "immutable" not in rv.headers.get("Cache-Control", "")

    def test_immutable_cache_when_max_age_positive(self, app, client):
        app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 43200
        rv = client.get(EXISTING_STATIC)
        assert rv.status_code == 200
        assert rv.headers["Cache-Control"] == "public, max-age=43200, immutable"


class TestHotlinkProtection:
    def test_foreign_referer_blocked(self, client):
        rv = client.get(
            "/static/banner/whatever.jpg",
            headers={"Referer": "http://evil.example.com/steal"},
        )
        assert rv.status_code == 403

    def test_empty_referer_allowed(self, client):
        rv = client.get("/static/banner/whatever.jpg")
        assert rv.status_code != 403

    def test_same_origin_referer_allowed(self, client):
        rv = client.get(
            "/static/banner/whatever.jpg",
            headers={"Referer": "http://localhost:80/"},
        )
        assert rv.status_code != 403

    def test_whitelisted_host_referer_allowed(self, app, client):
        app.config["HOST_WHITELIST"] = ["friend.example.com"]
        rv = client.get(
            "/static/banner/whatever.jpg",
            headers={"Referer": "http://friend.example.com:8080/page"},
        )
        assert rv.status_code != 403

    def test_unprotected_static_not_hotlink_checked(self, client):
        """非保护路径（如第三方库）不参与防盗链。"""
        rv = client.get(
            EXISTING_STATIC,
            headers={"Referer": "http://evil.example.com/steal"},
        )
        assert rv.status_code == 200
