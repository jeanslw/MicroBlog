"""工具函数测试。"""

import os

from app.utils import (
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
    """upload_dir 应创建目录"""
    # 用 monkeypatch 重定向 static 根以避免污染真实目录
    import app.utils as utils

    orig_root = utils.project_root
    fake_root = str(tmp_path)
    utils.project_root = lambda: fake_root
    try:
        d = upload_dir("test_subdir")
        assert os.path.isdir(d)
        assert d.endswith(os.path.join("static", "test_subdir"))
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
    """to_abs_url_path 应将绝对路径转为 /static/..."""
    root = project_root()
    abs_path = os.path.join(root, "static", "uploads", "x.png")
    url = to_abs_url_path(abs_path)
    assert url.endswith("/static/uploads/x.png")
    assert url.startswith("/static/")


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


def test_collect_static_upload_urls():
    """应从 HTML 中提取 /static/uploads/ 图片 URL"""
    from app.utils import collect_static_upload_urls

    html = '<img src="/static/uploads/a.png"><img src="/static/uploads/b.jpg?x=1">'
    urls = collect_static_upload_urls(html)
    assert "/static/uploads/a.png" in urls
    assert "/static/uploads/b.jpg" in urls
    assert collect_static_upload_urls("") == set()
    assert collect_static_upload_urls("<p>no image</p>") == set()


def test_remove_static_upload(tmp_path):
    """仅删除 uploads 目录内文件，且防路径穿越"""
    import app.utils as utils
    from app.utils import remove_static_upload

    orig_root = utils.project_root
    utils.project_root = lambda: str(tmp_path)
    try:
        f = tmp_path / "static" / "uploads" / "del.png"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
        assert remove_static_upload("/static/uploads/del.png") is True
        assert not f.exists()
        # 不存在的文件返回 False（幂等）
        assert remove_static_upload("/static/uploads/missing.png") is False
        # 外部 URL 不删
        assert remove_static_upload("https://evil.com/static/uploads/x.png") is False
        # 路径穿越被拒绝
        assert remove_static_upload("/static/uploads/../../evil.txt") is False
        assert not (tmp_path / "evil.txt").exists()
    finally:
        utils.project_root = orig_root
