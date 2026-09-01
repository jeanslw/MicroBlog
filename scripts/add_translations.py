"""一次性补翻译词条到 messages.po 并编译 messages.mo"""
from pathlib import Path

from babel.messages.catalog import Message
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po, write_po

ROOT = Path(__file__).resolve().parent.parent

new_entries = {
    'zh_CN': [
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
    ],
    'en': [
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
    ],
}

for locale, entries in new_entries.items():
    po_path = ROOT / f'translations/{locale}/LC_MESSAGES/messages.po'
    mo_path = ROOT / f'translations/{locale}/LC_MESSAGES/messages.mo'
    with po_path.open('rb') as f:
        catalog = read_po(f)
    existing = {m.id for m in catalog if m.id}
    added = 0
    for src, tgt in entries:
        if src in existing:
            continue
        catalog[src] = Message(id=src, string=tgt, locations=[])
        added += 1
    with po_path.open('wb') as f:
        write_po(f, catalog)
    with mo_path.open('wb') as f:
        write_mo(f, catalog)
    total = sum(1 for m in catalog if m.id)
    print(f'{locale}: +{added} entries, total={total}')
