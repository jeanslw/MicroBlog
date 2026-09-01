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


def strip_html(raw_html: str, max_len: int = 220) -> str:
    """去除 HTML 标签,提取纯文本摘要"""
    if not raw_html:
        return ""
    # nh3.clean 已剥离 script/style,再剥离所有标签
    text = nh3.clean(raw_html, tags=set())
    # 解码常见 HTML 实体（nh3 已转义,这里只处理常见残留）
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
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


def upload_dir(subdir: str = "uploads") -> str:
    """返回 static/{subdir} 绝对路径并自动创建"""
    path = os.path.join(project_root(), "static", subdir)
    os.makedirs(path, exist_ok=True)
    return path


# ── 上传文件清理（删除文章/换图时回收磁盘空间） ─────────────
# 本项目上传 URL 不带查询参数,排除 ? 避免把 ?x=1 误当文件名
_UPLOAD_URL_RE = re.compile(r"/static/uploads/[^\"'\s<>?]+")


def collect_static_upload_urls(html: str) -> set[str]:
    """从 HTML 内容中提取 /static/uploads/ 图片 URL 集合"""
    if not html:
        return set()
    return set(_UPLOAD_URL_RE.findall(html))


def remove_static_upload(url: str | None) -> bool:
    """安全删除 static/uploads 下的文件。

    - 仅处理 /static/uploads/ 开头的 URL（外部 http(s) 背景图不删）
    - 解析后的绝对路径必须仍位于 uploads 目录内（防路径穿越）
    - 文件不存在视为已删除,返回 False 表示未执行删除
    """
    if not url or "/static/uploads/" not in url:
        return False
    rel = url.split("/static/uploads/", 1)[1].split("?", 1)[0]
    upload_root = os.path.abspath(upload_dir("uploads"))
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
    """把项目内文件绝对路径转换为 URL 路径 /static/..."""
    root = project_root().replace("\\", "/")
    path = abs_path.replace("\\", "/")
    if path.startswith(root):
        return path[len(root) :]
    return path
