import re
import traceback
from html.parser import HTMLParser
from math import ceil
from config import PAGE_SIZE
from app.db import get_db, DictCursor


# 允许的 HTML 标签（白名单）
_ALLOWED_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "a", "img", "strong", "em", "b", "i", "u", "s", "del", "ins", "sub", "sup",
    "ul", "ol", "li", "blockquote", "pre", "code", "br", "hr",
    "table", "thead", "tbody", "tr", "th", "td", "caption",
    "span", "div", "section", "article", "header", "footer",
}
# 自闭合标签
_VOID_TAGS = {"br", "hr", "img"}

# 允许的属性
_ALLOWED_ATTRS = {
    "a": {"href", "title", "target", "rel"},
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


class _HTMLSanitizer(HTMLParser):
    """移除危险标签和属性的 HTML 净化器"""

    def __init__(self):
        super().__init__()
        self._result = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        if self._skip_depth > 0:
            self._skip_depth += 1
            return
        if tag_lower not in _ALLOWED_TAGS:
            self._skip_depth = 1  # 跳过整棵子树
            return
        allowed_attr = _ALLOWED_ATTRS.get(tag_lower, set())
        safe = []
        for name, val in attrs:
            name_lower = name.lower()
            if name_lower in allowed_attr:
                # 过滤 javascript: 伪协议
                if name_lower == "href" and val.strip().lower().startswith("javascript:"):
                    continue
                if name_lower.startswith("on"):
                    continue
                safe.append(f'{name}="{val}"')
        attr_str = (" " + " ".join(safe)) if safe else ""
        self._result.append(f"<{tag}{attr_str}>")

    def handle_endtag(self, tag):
        if self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if tag.lower() in _ALLOWED_TAGS and tag.lower() not in _VOID_TAGS:
            self._result.append(f"</{tag}>")

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        self._result.append(data)

    def handle_startendtag(self, tag, attrs):
        # 自闭合标签如 <br/> <img/>
        self.handle_starttag(tag, attrs)

    def handle_entityref(self, name):
        if self._skip_depth == 0:
            self._result.append(f"&{name};")

    def handle_charref(self, name):
        if self._skip_depth == 0:
            self._result.append(f"&#{name};")

    def get_result(self):
        return "".join(self._result)


def sanitize_html(raw_html):
    """净化 HTML，移除 XSS 攻击向量（script/iframe/on* 事件等）"""
    if not raw_html:
        return ""
    sanitizer = _HTMLSanitizer()
    sanitizer.feed(raw_html)
    return sanitizer.get_result()


def strip_html(raw_html):
    """去除 HTML 标签，提取纯文本摘要（先移除 script/style，再去除标签）"""
    if not raw_html:
        return ""
    # 先移除 script / style 标签及其内容
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw_html, flags=re.DOTALL | re.IGNORECASE)
    # 移除注释
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    # 移除所有 HTML 标签
    text = re.sub(r'<[^>]*>', '', text)
    # 解码常见 HTML 实体
    text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&amp;', '&').replace('&quot;', '"').replace('&#39;', "'")
    # 合并空白
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > 220:
        return text[:220] + "..."
    return text


def get_article_list(offset, limit, cid=None):
    """获取文章列表（分页 + 可选栏目筛选），仅包含评论数不查评论详情"""
    try:
        db = get_db()
        cur = db.cursor(DictCursor)

        if cid:
            cur.execute("""
                SELECT a.*, COUNT(c.id) AS comment_num
                FROM article a
                LEFT JOIN comment c ON a.id = c.article_id
                WHERE a.status='publish' AND a.category_id=%s
                GROUP BY a.id ORDER BY a.create_time DESC LIMIT %s,%s
            """, (cid, offset, limit))
            article_data = cur.fetchall()
            cur.execute(
                "SELECT COUNT(id) AS total FROM article WHERE status='publish' AND category_id=%s", (cid,))
        else:
            cur.execute("""
                SELECT a.*, COUNT(c.id) AS comment_num
                FROM article a
                LEFT JOIN comment c ON a.id = c.article_id
                WHERE a.status='publish'
                GROUP BY a.id ORDER BY a.create_time DESC LIMIT %s,%s
            """, (offset, limit))
            article_data = cur.fetchall()
            cur.execute(
                "SELECT COUNT(id) AS total FROM article WHERE status='publish'")

        total = cur.fetchone()["total"]
        total_page = ceil(total / PAGE_SIZE) if total > 0 else 1

        # 只为每篇文章生成摘要（不再嵌套查询评论）
        for art in article_data:
            art["brief"] = strip_html(art["content"])
        cur.close()
        return article_data, total_page
    except Exception:
        print("=====获取文章列表失败=====")
        traceback.print_exc()
        return [], 1


def get_article_detail(aid):
    """获取文章详情 + 评论 + 回复（批量查询，避免 N+1）"""
    try:
        db = get_db()
        cur = db.cursor(DictCursor)
        cur.execute("SELECT * FROM article WHERE id=%s", (aid,))
        article = cur.fetchone()
        if not article:
            cur.close()
            return None, []

        # 输出前净化 HTML，防止 XSS
        article["content"] = sanitize_html(article["content"])

        # 一次性查出所有评论
        cur.execute(
            "SELECT * FROM comment WHERE article_id=%s ORDER BY create_time", (aid,))
        comments = cur.fetchall()

        if comments:
            # 收集所有评论 ID，一次查出所有回复
            comment_ids = [com["id"] for com in comments]
            placeholders = ",".join(["%s"] * len(comment_ids))
            cur.execute(
                f"SELECT * FROM reply WHERE comment_id IN ({placeholders}) ORDER BY create_time",
                comment_ids
            )
            all_replies = cur.fetchall()

            # 按 comment_id 分组回复
            reply_map = {}
            for r in all_replies:
                reply_map.setdefault(r["comment_id"], []).append(r)

            for com in comments:
                com["reply_list"] = reply_map.get(com["id"], [])

        cur.close()
        return article, comments
    except Exception:
        print("=====获取文章详情失败=====")
        traceback.print_exc()
        return None, []
