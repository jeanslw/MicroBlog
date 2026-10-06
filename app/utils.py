"""通用工具函数。

- HTML 净化（基于 nh3,替代脆弱的自实现 regex/HTMLParser 方案）
- 纯文本提取（摘要）
- 图片安全处理（Pillow 解压炸弹防护）
- 文件名安全化 + UUID 命名
"""

import os
import re
import uuid

import nh3
from PIL import Image, ImageFile, ImageSequence
from werkzeug.utils import secure_filename

# ── HTML 净化（白名单） ─────────────────────────────────
# 允许的标签
ALLOWED_TAGS = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "a",
    "img",
    "strong",
    "em",
    "b",
    "i",
    "u",
    "s",
    "del",
    "ins",
    "sub",
    "sup",
    "ul",
    "ol",
    "li",
    "blockquote",
    "pre",
    "code",
    "br",
    "hr",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "caption",
    "span",
    "div",
    "section",
    "article",
    "header",
    "footer",
    "video",
    "audio",
    "source",
    "track",
}

# 允许的属性
ALLOWED_ATTRS = {
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "title", "width", "height"},
    "code": {"class"},
    "span": {"class", "style"},
    "div": {"class", "style"},
    "pre": {"class"},
    "table": {"class", "border"},
    "th": {"class", "colspan", "rowspan"},
    "td": {"class", "colspan", "rowspan"},
    "p": {"class", "style"},
    "h1": {"class"},
    "h2": {"class"},
    "h3": {"class"},
    "h4": {"class"},
    "h5": {"class"},
    "h6": {"class"},
    "blockquote": {"class"},
    "video": {"src", "controls", "width", "height", "class", "style", "poster", "preload"},
    "audio": {"src", "controls", "class", "style", "preload"},
    "source": {"src", "type"},
    "track": {"src", "kind", "srclang", "label", "default"},
}

# URL 协议白名单（防 javascript: data: 等）
ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}


def sanitize_html(raw_html: str) -> str:
    """净化 HTML,移除 XSS 攻击向量（script/iframe/on* 事件/javascript: 等）"""
    if not raw_html:
        return ""
    return nh3.clean(
        raw_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        url_schemes=ALLOWED_URL_SCHEMES,
        strip_comments=True,
        link_rel="noopener noreferrer nofollow",
    )


def strip_html(raw_html: str, max_len: int | None = 220) -> str:
    """去除 HTML 标签,提取纯文本摘要。

    max_len=None 表示不截断，适用于全文字数统计等场景。
    """
    if not raw_html:
        return ""
    # nh3.clean 已剥离 script/style,再剥离所有标签
    text = nh3.clean(raw_html, tags=set())
    # 解码常见 HTML 实体（nh3 已转义,这里只处理常见残留）
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
    text = re.sub(r"\s+", " ", text).strip()
    if max_len is not None and len(text) > max_len:
        return text[:max_len] + "..."
    return text


# ── 图片处理（带解压炸弹防护） ───────────────────────────
def configure_pillow(max_pixels: int = 50_000_000):
    """配置 Pillow 安全参数,应用启动时调用一次"""
    Image.MAX_IMAGE_PIXELS = max_pixels
    ImageFile.LOAD_TRUNCATED_IMAGES = False  # 默认 False 更严格,损坏图直接报错


def process_and_save_image(
    file_storage,
    save_path: str,
    ext: str,
    max_width: int = 1200,
    quality: int = 85,
) -> None:
    """打开上传图,必要时等比缩放,按格式保存到 save_path。

    Raises:
        PIL.UnidentifiedImageError, OSError, ValueError 等异常由调用方处理
    """
    image = Image.open(file_storage)
    ext_lower = ext.lower()

    if ext_lower == "gif":
        # GIF 单独处理:逐帧缩放 + 保留动画
        _save_gif(image, save_path, max_width)
        return

    # 非 GIF：等比缩放（仅当超过 max_width 时）
    if image.width > max_width:
        ratio = max_width / image.width
        new_height = int(image.height * ratio)
        image = image.resize((max_width, new_height), Image.LANCZOS)

    if ext_lower in ("jpg", "jpeg"):
        # JPEG 不支持透明通道,RGBA/P 模式需先转 RGB
        if image.mode in ("RGBA", "P", "LA"):
            image = image.convert("RGB")
        image.save(save_path, "JPEG", quality=quality, optimize=True)
    elif ext_lower == "png":
        image.save(save_path, "PNG", optimize=True)
    else:
        # 兜底：原格式
        image.save(save_path)


def _save_gif(image: Image.Image, save_path: str, max_width: int) -> None:
    """保存 GIF 并保留动画帧;超宽时逐帧等比缩放"""
    frames = list(ImageSequence.Iterator(image)) or [image]
    scaled: list[Image.Image] = []
    for frame in frames:
        if frame.width > max_width:
            ratio = max_width / frame.width
            frame = frame.resize((max_width, int(frame.height * ratio)), Image.LANCZOS)
        scaled.append(frame)
    scaled[0].save(
        save_path,
        "GIF",
        save_all=True,
        append_images=scaled[1:],
        optimize=True,
        loop=0,
    )


def process_and_resize_logo(
    file_storage,
    save_path: str,
    ext: str,
    max_edge: int = 400,
    quality: int = 90,
) -> None:
    """打开 Logo 图,等比缩放使长边不超过 max_edge,按格式保存。

    Logo 过大时自动缩小（thumbnail 保持宽高比、不拉伸），输出尺寸
    始终控制在限制内。Raises 交由调用方处理。
    """
    image = Image.open(file_storage)
    image.thumbnail((max_edge, max_edge), Image.LANCZOS)

    ext_lower = ext.lower()
    if ext_lower in ("jpg", "jpeg"):
        # JPEG 不支持透明通道,RGBA/P 模式需先转 RGB
        if image.mode in ("RGBA", "P", "LA"):
            image = image.convert("RGB")
        image.save(save_path, "JPEG", quality=quality, optimize=True)
    elif ext_lower == "png":
        image.save(save_path, "PNG", optimize=True)
    else:
        # webp 等：按扩展名自动推导格式保存
        image.save(save_path)


def build_safe_filename(original_filename: str, base_name_max_len: int = 100) -> str:
    """生成安全且唯一的文件名：{uuid}_{base}.{ext}

    secure_filename 处理中文/特殊字符可能返回空,用 uuid 兜底。
    去除 base 自带的扩展名避免双扩展（xxx.png.png）。
    """
    if "." not in original_filename:
        raise ValueError("文件名缺少扩展名")
    ext = original_filename.rsplit(".", 1)[1].lower()
    base = secure_filename(original_filename)
    if base:
        base = os.path.splitext(base)[0]
    if not base:
        base = uuid.uuid4().hex
    if len(base) > base_name_max_len:
        base = base[:base_name_max_len]
    return f"{uuid.uuid4().hex}_{base}.{ext}"


# ── 项目根目录绝对路径（避免相对路径在不同 cwd 下失效） ─────
def project_root() -> str:
    """返回项目根目录绝对路径（app/ 的父目录）"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 上传资源目录（项目根 uploads/，与内置 static/ 分离） ─────
# banner —— 轮播图；image —— 正文插图 / Logo / 头像 / 自定义背景
# （image 下再分 avatar / logo / backgrounds 子目录）。
UPLOAD_CATEGORIES = ("banner", "image")


def uploads_root() -> str:
    """返回项目根 uploads/ 目录绝对路径并自动创建"""
    path = os.path.join(project_root(), "uploads")
    os.makedirs(path, exist_ok=True)
    return path


def upload_dir(category: str = "image", subdir: str = "") -> str:
    """返回 uploads/<category>[/<subdir>] 绝对路径并自动创建。

    category 仅允许 UPLOAD_CATEGORIES 中的值，防止调用方拼出越界目录。
    """
    if category not in UPLOAD_CATEGORIES:
        raise ValueError(f"非法上传分类: {category}")
    parts = [uploads_root(), category]
    if subdir:
        parts.append(subdir.strip("/\\"))
    path = os.path.join(*parts)
    os.makedirs(path, exist_ok=True)
    return path


# ── 上传文件清理（删除文章/换图时回收磁盘空间） ─────────────
# 本项目上传 URL 不带查询参数,排除 ? 避免把 ?x=1 误当文件名。
# 同时识别新版 /uploads/(banner|image)/ 与旧版 /static/(banner|uploads)/，
# 后者来自迁移前写入数据库的历史记录（旧 URL 由 301 路由继续可访问）。
_UPLOAD_URL_PREFIXES = (
    ("/uploads/banner/", "banner"),
    ("/uploads/image/", "image"),
    ("/static/banner/", "banner"),
    ("/static/uploads/", "image"),
)
_UPLOAD_URL_RE = re.compile(
    r"/(?:uploads/(?:banner|image)|static/(?:banner|uploads))/[^\"'\s<>?]+"
)


def collect_upload_urls(html: str) -> set[str]:
    """从 HTML 内容中提取上传图片 URL 集合（新旧路径均识别）"""
    if not html:
        return set()
    return set(_UPLOAD_URL_RE.findall(html))


def _parse_upload_url(url: str | None) -> tuple[str, str] | None:
    """把上传资源 URL 解析为 (category, 相对路径)；非上传 URL 返回 None。

    仅接受站内相对路径（以 "/" 开头）：外部 http(s) 图片 URL（如自定义背景）
    不属于本站 uploads，绝不能因为其路径里"恰好包含" /uploads/image/ 段
    （例：https://evil.com/x/uploads/image/a.png）而被当作本地文件处理。
    前缀一律用 startswith 常量匹配，不用 `prefix in url` 子串判断。
    """
    if not url or not url.startswith("/"):
        return None
    for prefix, category in _UPLOAD_URL_PREFIXES:
        if url.startswith(prefix):
            rel = url[len(prefix) :].split("?", 1)[0]
            return category, rel
    return None


def remove_uploaded_file(url: str | None) -> bool:
    """安全删除 uploads 下的文件（兼容旧版 /static/... URL）。

    - 仅处理上传目录的 URL（外部 http(s) 背景图不删）
    - 解析后的绝对路径必须仍位于目标分类目录内（防路径穿越）
    - 文件不存在视为已删除,返回 False 表示未执行删除
    """
    parsed = _parse_upload_url(url)
    if not parsed:
        return False
    category, rel = parsed
    upload_root = os.path.abspath(upload_dir(category))
    abs_path = os.path.abspath(os.path.join(upload_root, rel))
    if not abs_path.startswith(upload_root + os.sep):
        return False
    try:
        if os.path.isfile(abs_path):
            os.remove(abs_path)
            return True
    except OSError:
        pass
    return False


def to_abs_url_path(abs_path: str) -> str:
    """把项目内文件绝对路径转换为 URL 路径（/uploads/... 或 /static/...）"""
    root = project_root().replace("\\", "/")
    path = abs_path.replace("\\", "/")
    if path.startswith(root):
        return path[len(root) :]
    return path


def migrate_legacy_upload_dirs() -> list[str]:
    """一次性迁移旧上传目录到 uploads/（幂等，供启动时调用）。

    static/banner  -> uploads/banner
    static/uploads -> uploads/image
    目标不存在时整体改名；目标已存在且非空时跳过（避免覆盖，由管理员手工合并）。
    返回迁移说明列表，交由调用方写日志。
    """
    moved: list[str] = []
    for old_name, category in (("banner", "banner"), ("uploads", "image")):
        old = os.path.join(project_root(), "static", old_name)
        new = upload_dir(category)
        if not os.path.isdir(old):
            continue
        if os.path.isdir(new) and os.listdir(new):
            continue
        if os.path.isdir(new):
            # 目标存在但为空：删掉空目录再改名
            os.rmdir(new)
        os.rename(old, new)
        moved.append(f"上传目录已迁移: {os.path.join('static', old_name)} -> uploads/{category}")
    return moved


# ── 站内资源是否存在（跨机恢复后上传文件可能缺失） ──────
def asset_url_exists(url: str | None) -> bool:
    """判断站点资源 URL 指向的文件在本地是否真实存在。

    用途是「渲染前兜底」：数据库备份不含 uploads/ 下的上传文件
    （Logo / 头像 / 背景图 / 正文插图 / 轮播图），把备份恢复到另一台机器
    或容器后，库里记录的 URL 仍在、文件却已丢失，浏览器会渲染成破图；
    而带 alt 的 ``<img>`` 还会把 alt 文本画出来——导航栏 Logo 的 alt
    正是站点名，页面上会出现「My Blog My Blog」这种数据错乱现象。

    - 外部 http(s) URL：无法本地校验，一律视为存在（交浏览器处理）
    - ``/uploads/...``（含旧版 ``/static/banner|uploads``）：映射到 uploads 目录校验
    - ``/static/...`` 或 ``static/...``：内置静态资源，映射到 static 目录校验
    - 空值 / 其他形式（``data:`` 等）：False
    """
    if not url:
        return False
    if url.startswith(("http://", "https://")):
        return True
    # 上传资源（新版 + 旧版路径）
    parsed = _parse_upload_url(url)
    if parsed:
        category, rel = parsed
        upload_root = os.path.abspath(upload_dir(category))
        abs_path = os.path.abspath(os.path.join(upload_root, rel))
        if not abs_path.startswith(upload_root + os.sep):
            return False
        return os.path.isfile(abs_path)
    # 内置静态资源（favicon、内置背景图、第三方库等）
    if "/static/" in url:
        rel = url.split("/static/", 1)[1]
    elif url.startswith("static/"):
        rel = url[len("static/") :]
    else:
        return False
    static_root = os.path.abspath(os.path.join(project_root(), "static"))
    abs_path = os.path.abspath(os.path.join(static_root, rel.split("?", 1)[0]))
    if not abs_path.startswith(static_root + os.sep):
        return False
    return os.path.isfile(abs_path)
