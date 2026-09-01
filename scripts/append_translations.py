"""安全追加翻译词条(只 append,不覆盖原 PO 头部和现有词条)"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

entries = [
    ('zh_CN', [
        ('文章管理', '文章管理'),
        ('草稿管理', '草稿管理'),
        ('撤回文章', '撤回文章'),
        ('轮播图列表', '轮播图列表'),
        ('撤回所有轮播图', '撤回所有轮播图'),
        ('撤回将删除全部轮播图（含图片文件），确认继续？',
         '撤回将删除全部轮播图（含图片文件），确认继续？'),
        ('当前没有可撤回的轮播图', '当前没有可撤回的轮播图'),
        ('已撤回全部轮播图', '已撤回全部轮播图'),
        ('撤回失败,请稍后重试', '撤回失败,请稍后重试'),
        ('暂无已发布文章', '暂无已发布文章'),
        ('撤回', '撤回'),
        ('点击撤回即可将已发布的文章移回草稿箱（首页将不再展示），但不会删除任何内容。',
         '点击撤回即可将已发布的文章移回草稿箱（首页将不再展示），但不会删除任何内容。'),
        ('确定将该文章撤回至草稿箱？', '确定将该文章撤回至草稿箱？'),
        ('已撤回至草稿箱', '已撤回至草稿箱'),
        ('文章不存在', '文章不存在'),
    ]),
    ('en', [
        ('Article Management', 'Article Management'),
        ('Drafts', 'Drafts'),
        ('Recall Articles', 'Recall Articles'),
        ('Banner List', 'Banner List'),
        ('Withdraw All Banners', 'Withdraw All Banners'),
        ('Withdraw will delete all banners (including image files). Continue?',
         'Withdraw will delete all banners (including image files). Continue?'),
        ('No banners to withdraw', 'No banners to withdraw'),
        ('All banners withdrawn', 'All banners withdrawn'),
        ('Withdraw failed, please retry later',
         'Withdraw failed, please retry later'),
        ('No published articles', 'No published articles'),
        ('Recall', 'Recall'),
        ('Click recall to move a published article back to drafts '
         '(it will no longer appear on the home page); no content is deleted.',
         'Click recall to move a published article back to drafts '
         '(it will no longer appear on the home page); no content is deleted.'),
        ('Confirm to recall this article to drafts?',
         'Confirm to recall this article to drafts?'),
        ('Recalled to drafts', 'Recalled to drafts'),
        ('Article not found', 'Article not found'),
    ]),
]

for locale, items in entries:
    po = ROOT / f'translations/{locale}/LC_MESSAGES/messages.po'
    text = po.read_text(encoding='utf-8')
    existing = set()
    for m in re.finditer(
        r'^msgid "((?:[^"\\]|\\.)*)"', text, re.M
    ):
        if m.group(1):
            existing.add(m.group(1))
    added = 0
    body = []
    for src, tgt in items:
        if src in existing:
            continue
        body.append(f'\nmsgid "{src}"\nmsgstr "{tgt}"')
        added += 1
    if body:
        new_text = text.rstrip() + '\n' + '\n'.join(body) + '\n'
        po.write_text(new_text, encoding='utf-8')
    print(f'{locale}: +{added} new entries (existing was {len(existing)})')
