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
from PIL import Image, ImageFile
from werkzeug.utils import secure_filename


# ── HTML 净化（白名单） ─────────────────────────────────
# 允许的标签
ALLOWED_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "a", "img", "strong", "em", "b", "i", "u", "s", "del", "ins", "sub", "sup",
    "ul", "ol", "li", "blockquote", "pre", "code", "br", "hr",
    "table", "thead", "tbody", "tr", "th", "td", "caption",
    "span", "div", "section", "article", "header", "footer",
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
    "h1": {"class"}, "h2": {"class"}, "h3": {"class"},
    "h4": {"class"}, "h5": {"class"}, "h6": {"class"},
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

    # 等比缩放（仅当超过 max_width 时）
    if image.width > max_width:
        ratio = max_width / image.width
        new_height = int(image.height * ratio)
        image = image.resize((max_width, new_height), Image.LANCZOS)

    ext_lower = ext.lower()
    if ext_lower in ("jpg", "jpeg"):
        # JPEG 不支持透明通道,RGBA/P 模式需先转 RGB
        if image.mode in ("RGBA", "P", "LA"):
            image = image.convert("RGB")
        image.save(save_path, "JPEG", quality=quality, optimize=True)
    elif ext_lower == "png":
        image.save(save_path, "PNG", optimize=True)
    elif ext_lower == "gif":
        image.save(save_path, "GIF")
    else:
        # 兜底：原格式
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


def to_abs_url_path(abs_path: str) -> str:
    """把项目内文件绝对路径转换为 URL 路径 /static/..."""
    root = project_root().replace("\\", "/")
    path = abs_path.replace("\\", "/")
    if path.startswith(root):
        return path[len(root):]
    return path
