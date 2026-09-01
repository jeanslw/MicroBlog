"""一次性编译所有 messages.mo"""
from pathlib import Path

from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po

ROOT = Path(__file__).resolve().parent.parent

for locale_dir in (ROOT / 'translations').iterdir():
    po = locale_dir / 'LC_MESSAGES/messages.po'
    mo = locale_dir / 'LC_MESSAGES/messages.mo'
    if not po.exists():
        continue
    with po.open('rb') as f:
        catalog = read_po(f)
    with mo.open('wb') as f:
        write_mo(f, catalog)
    print(f'{po.relative_to(ROOT)} -> {mo.relative_to(ROOT)}: '
          f'{sum(1 for m in catalog if m.id)} entries')
