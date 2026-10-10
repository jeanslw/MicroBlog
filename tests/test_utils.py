"""工具函数测试。"""

import os

import pytest

from app.utils import (
    asset_url_exists,
    build_safe_filename,
    configure_pillow,
    process_and_save_image,
    project_root,
    to_abs_url_path,
    upload_dir,
)


def test_project_root_exists():
    """project_root 应返回存在的目录"""
    root = project_root()
    assert os.path.isdir(root)
    assert os.path.isdir(os.path.join(root, "app"))
    assert os.path.isdir(os.path.join(root, "templates"))


def test_upload_dir_creates_directory(tmp_path):
    """upload_dir 应在 uploads/ 下创建分类目录，非法分类抛 ValueError"""
    import app.utils as utils

    orig_root = utils.project_root
    utils.project_root = lambda: str(tmp_path)
    try:
        d = upload_dir("image", "avatar")
        assert os.path.isdir(d)
        assert d.endswith(os.path.join("uploads", "image", "avatar"))
        d2 = upload_dir("banner")
        assert d2.endswith(os.path.join("uploads", "banner"))
        with pytest.raises(ValueError):
            upload_dir("etc")
    finally:
        utils.project_root = orig_root


def test_process_and_save_image_png(tmp_path):
    """PNG 图片应能被保存"""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (100, 80), "red").save(buf, format="PNG")
    buf.seek(0)
    out = tmp_path / "out.png"
    process_and_save_image(buf, str(out), "png")
    assert out.exists()
    # 应可被重新打开
    with Image.open(out) as im:
        assert im.format == "PNG"


def test_process_and_save_image_jpeg_convert(tmp_path):
    """RGBA 模式 JPEG 应自动转换"""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (60, 60), (255, 0, 0, 128)).save(buf, format="PNG")
    buf.seek(0)
    out = tmp_path / "out.jpg"
    process_and_save_image(buf, str(out), "jpg")
    assert out.exists()
    with Image.open(out) as im:
        assert im.format == "JPEG"


def test_process_and_save_image_resize(tmp_path):
    """超过 max_width 应被缩放"""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (2000, 1000), "blue").save(buf, format="PNG")
    buf.seek(0)
    out = tmp_path / "resized.png"
    process_and_save_image(buf, str(out), "png", max_width=500)
    with Image.open(out) as im:
        assert im.width == 500
        assert im.height == 250


def test_process_and_save_image_gif(tmp_path):
    """GIF 格式应能保存"""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "green").save(buf, format="GIF")
    buf.seek(0)
    out = tmp_path / "out.gif"
    process_and_save_image(buf, str(out), "gif")
    assert out.exists()


def test_configure_pillow_sets_max_pixels():
    """configure_pillow 应设置 MAX_IMAGE_PIXELS"""
    from PIL import Image

    configure_pillow(12345)
    assert Image.MAX_IMAGE_PIXELS == 12345


def test_to_abs_url_path():
    """to_abs_url_path 应将绝对路径转为 /uploads/... 或 /static/... URL"""
    root = project_root()
    url = to_abs_url_path(os.path.join(root, "uploads", "image", "x.png"))
    assert url.endswith("/uploads/image/x.png")
    assert url.startswith("/uploads/")
    url_static = to_abs_url_path(os.path.join(root, "static", "favicon.ico"))
    assert url_static == "/static/favicon.ico"


def test_build_safe_filename_long_base():
    """超长 base 应被截断"""
    long_name = "a" * 200 + ".png"
    name = build_safe_filename(long_name, base_name_max_len=50)
    # 应包含 .png 且整体长度合理
    assert name.endswith(".png")
    base = name.rsplit(".", 1)[0]
    # base 形如 {uuid}_{truncated}
    assert len(base) <= 50 + 33  # 50 截断 + 32 uuid + 分隔符


def test_process_and_save_image_gif_keeps_frames(tmp_path):
    """多帧 GIF 应保留动画帧"""
    import io

    from PIL import Image

    buf = io.BytesIO()
    frames = [Image.new("RGB", (40, 40), c) for c in ("red", "green", "blue")]
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    buf.seek(0)
    out = tmp_path / "anim.gif"
    process_and_save_image(buf, str(out), "gif")
    with Image.open(out) as im:
        assert im.n_frames >= 2


def test_collect_upload_urls():
    """应从 HTML 中提取上传图片 URL（新版 + 旧版路径均识别）"""
    from app.utils import collect_upload_urls

    html = (
        '<img src="/uploads/image/a.png">'
        '<img src="/uploads/banner/b.jpg">'
        '<img src="/static/uploads/c.jpg?x=1">'
        '<img src="/static/banner/d.png">'
        '<img src="https://example.com/e.png">'
    )
    urls = collect_upload_urls(html)
    assert "/uploads/image/a.png" in urls
    assert "/uploads/banner/b.jpg" in urls
    assert "/static/uploads/c.jpg" in urls
    assert "/static/banner/d.png" in urls
    # 收集结果必须全部是站内相对路径：不得混入外部 URL
    assert all(u.startswith("/") and not u.startswith(("http://", "https://")) for u in urls)
    assert collect_upload_urls("") == set()
    assert collect_upload_urls("<p>no image</p>") == set()


def test_remove_uploaded_file(tmp_path):
    """仅删除 uploads 目录内文件，新旧 URL 均支持，且防路径穿越"""
    import app.utils as utils
    from app.utils import remove_uploaded_file

    utils.project_root = lambda: str(tmp_path)
    try:
        f = tmp_path / "uploads" / "image" / "del.png"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
        # 新版 URL
        assert remove_uploaded_file("/uploads/image/del.png") is True
        assert not f.exists()
        # 不存在的文件返回 False（幂等）
        assert remove_uploaded_file("/uploads/image/missing.png") is False
        # 旧版 URL 映射到新物理目录
        f2 = tmp_path / "uploads" / "banner" / "old.png"
        f2.parent.mkdir(parents=True, exist_ok=True)
        f2.write_bytes(b"x")
        assert remove_uploaded_file("/static/banner/old.png") is True
        assert not f2.exists()
        # 外部 URL 不删
        assert remove_uploaded_file("https://evil.com/uploads/image/x.png") is False
        # 外部 URL 的路径段里"嵌入"上传前缀同样不处理（不得误伤同名本地文件）
        keep = tmp_path / "uploads" / "image" / "keep.png"
        keep.write_bytes(b"x")
        assert remove_uploaded_file("https://evil.com/p/uploads/image/keep.png") is False
        assert keep.exists()  # 本地 keep.png 必须还在
        # 路径穿越被拒绝
        assert remove_uploaded_file("/uploads/image/../../evil.txt") is False
        assert not (tmp_path / "evil.txt").exists()
    finally:
        utils.project_root = project_root


def test_asset_url_exists(tmp_path, monkeypatch):
    """站内资源存在性判断（跨机恢复后上传文件缺失的渲染兜底依据）"""
    import app.utils as utils

    monkeypatch.setattr(utils, "project_root", lambda: str(tmp_path))
    f = tmp_path / "uploads" / "image" / "logo" / "a.png"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"x")
    # 新版上传路径
    assert asset_url_exists("/uploads/image/logo/a.png") is True
    assert asset_url_exists("/uploads/image/logo/a.png?v=1") is True
    assert asset_url_exists("/uploads/image/logo/missing.png") is False
    # 旧版上传路径也映射到新目录
    assert asset_url_exists("/static/uploads/logo/a.png") is True
    # banner 分类
    bf = tmp_path / "uploads" / "banner" / "b.jpg"
    bf.parent.mkdir(parents=True, exist_ok=True)
    bf.write_bytes(b"x")
    assert asset_url_exists("/uploads/banner/b.jpg") is True
    assert asset_url_exists("/static/banner/b.jpg") is True
    # 内置静态资源（favicon 等）仍走 static 目录；兼容不带前导斜杠的写法
    sf = tmp_path / "static" / "favicon.ico"
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_bytes(b"x")
    assert asset_url_exists("/static/favicon.ico") is True
    assert asset_url_exists("static/favicon.ico") is True
    # 外部 URL 无法本地校验，视为存在（交浏览器处理）
    assert asset_url_exists("https://example.com/x.png") is True
    assert asset_url_exists("http://example.com/x.png") is True
    # 空值 / 其他形式
    assert asset_url_exists("") is False
    assert asset_url_exists(None) is False
    assert asset_url_exists("data:image/png;base64,AAAA") is False
    # 路径穿越不外溢到目标目录之外
    assert asset_url_exists("/uploads/image/../../app/__init__.py") is False
    assert asset_url_exists("/static/../app/__init__.py") is False


def test_migrate_legacy_upload_dirs(tmp_path, monkeypatch):
    """启动迁移：static/banner、static/uploads 应改名到 uploads/ 下（幂等）"""
    import app.utils as utils

    monkeypatch.setattr(utils, "project_root", lambda: str(tmp_path))
    # 旧目录及文件
    old_banner = tmp_path / "static" / "banner"
    old_banner.mkdir(parents=True)
    (old_banner / "b.jpg").write_bytes(b"x")
    old_uploads = tmp_path / "static" / "uploads"
    old_uploads.mkdir(parents=True)
    (old_uploads / "logo").mkdir()
    (old_uploads / "logo" / "l.png").write_bytes(b"x")

    messages = utils.migrate_legacy_upload_dirs()
    assert len(messages) == 2
    assert (tmp_path / "uploads" / "banner" / "b.jpg").is_file()
    assert (tmp_path / "uploads" / "image" / "logo" / "l.png").is_file()
    assert not old_banner.exists()
    assert not old_uploads.exists()
    # 再次调用：无旧目录，幂等无操作
    assert utils.migrate_legacy_upload_dirs() == []
