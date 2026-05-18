"""
patch_notes.py - 一次性：
1. 將 dev-note.md 合併到 DEVELOPMENT_NOTES.md 末尾
2. 刪除 docs/dev-note.md
3. 修正 index.html：按鈕放大、輸入範圍改 1-20A integer
"""
import pathlib, re

ROOT = pathlib.Path(__file__).parent

# ── 1. 合併 dev-note → DEVELOPMENT_NOTES ─────────────────────────────────────
dev_note = (ROOT / "docs" / "dev-note.md").read_text(encoding="utf-8")
notes    = (ROOT / "docs" / "DEVELOPMENT_NOTES.md").read_text(encoding="utf-8")

SEPARATOR = """

---

## 2026-05-18 ── Web UI 開發踩坑：編碼、渲染與快取問題

"""

# 取 dev-note.md 的主體（跳過第一行 H1）
lines = dev_note.splitlines()
body_start = next(i for i, l in enumerate(lines) if l.startswith("## "))
dev_body = "\n".join(lines[body_start:])

appended = notes.rstrip() + SEPARATOR + dev_body + "\n"
(ROOT / "docs" / "DEVELOPMENT_NOTES.md").write_text(appended, encoding="utf-8")
print("✓ 合併 dev-note → DEVELOPMENT_NOTES.md")

# 刪除 dev-note.md
(ROOT / "docs" / "dev-note.md").unlink()
print("✓ 刪除 docs/dev-note.md")

# ── 2. 修正 index.html ─────────────────────────────────────────────────────────
html_path = ROOT / "web" / "templates" / "index.html"
html = html_path.read_text(encoding="utf-8")

# 批次套用輸入：0.5-25.5 step=0.5 → 1-20 step=1
html = html.replace(
    'min="0.5" max="25.5" step="0.5"\n                                       placeholder="A" class="nominal-input"',
    'min="1" max="20" step="1"\n                                       placeholder="A" class="nominal-input"'
)
# 批次按鈕放大：btn btn-sm → btn
html = html.replace(
    '<button class="btn btn-sm" @click="setAllNominal">套用至全部通道</button>',
    '<button class="btn" @click="setAllNominal">套用至全部通道</button>'
)
# 個別通道輸入：0.5-25.5 step=0.5 → 1-20 step=1
html = html.replace(
    'min="0.5" max="25.5" step="0.5"\n                                                   :placeholder="ch.nominal_amps"',
    'min="1" max="20" step="1"\n                                                   :placeholder="ch.nominal_amps"'
)
# 個別設定按鈕放大：btn btn-sm → btn
html = html.replace(
    '<button class="btn btn-sm" @click="setNominal(ch.id)">設定</button>',
    '<button class="btn" @click="setNominal(ch.id)">設定</button>'
)
# 更新版本參數
html = html.replace("style.css?v=4.2.2\"", "style.css?v=4.2.2b\"")
html = html.replace("app.js?v=4.2.2\"", "app.js?v=4.2.2b\"")

html_path.write_text(html, encoding="utf-8")
print("✓ 修正 index.html（按鈕放大、輸入範圍 1-20A）")

# 驗證
t = html_path.read_text(encoding="utf-8")
checks = [
    ('按鈕放大', '<button class="btn" @click="setNominal' in t),
    ('批次按鈕放大', '<button class="btn" @click="setAllNominal' in t),
    ('範圍 1-20', 'min="1" max="20" step="1"' in t),
    ('無舊範圍', 'min="0.5"' not in t),
    ('版本更新', 'v=4.2.2b' in t),
    ('BOM', t.encode('utf-8')[:3] != b'\xef\xbb\xbf'),
]
for name, ok in checks:
    print(f"  {'✓' if ok else '✗'} {name}")

print("完成")
