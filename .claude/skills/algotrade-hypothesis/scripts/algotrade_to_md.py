"""Tải các bài ALGOTRADE Knowledge Hub (https://www.algotrade.vn/knowledge) thành Markdown.

python3 .claude/skills/algotrade-hypothesis/scripts/algotrade_to_md.py [thư_mục_ra]
→ mặc định docs/algotrade_knowledge_hub/NN_<module>__<slug>.md với `# Tiêu đề`, đề mục trong bài → `##`.
Trang Wix: thân bài nằm trong JSON nhúng dưới dạng HTML (`<body>…</body>` đã escape), không cần trình duyệt.
"""

from __future__ import annotations

import html
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "docs/algotrade_knowledge_hub"
INDEX = "https://www.algotrade.vn/knowledge"
MODULES = ["algorithmic-trading-concept", "9-step-process", "trading-strategy", "9-component-architecture",
           "specialized-intellect"]


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="ignore")


def article_urls() -> list[str]:
    pages = [get(INDEX)] + [get(f"{INDEX}/{m}") for m in MODULES]
    urls = {u for p in pages for u in re.findall(rf"{re.escape(INDEX)}/[a-z0-9-]+/[a-z0-9-]+", p)}
    return sorted(urls, key=lambda u: (MODULES.index(u.split("/")[-2]) if u.split("/")[-2] in MODULES else 99, u))


def title_of(page: str) -> str:
    m = re.search(r"<title>(.*?)</title>", page, re.S)
    return html.unescape(m.group(1).split("|")[0].strip()) if m else ""


def body_markdown(page: str) -> str:
    i = page.find("<body>\\n")
    j = page.find("<\\/body>", i)
    if i < 0 or j < 0:
        raise ValueError("không thấy thân bài nhúng")
    frag = json.loads('"' + page[i:j] + '"')
    frag = re.sub(r"<img[^>]*>", "", frag)
    frag = re.sub(r'<p class="heading-\d"[^>]*>(.*?)</p>', lambda m: f"\n\n## {m.group(1)}\n\n", frag, flags=re.S)
    frag = re.sub(r"<li[^>]*>", "\n- ", frag)
    frag = re.sub(r"<(?:p|h\d|tr)[^>]*>", "\n\n", frag)
    frag = re.sub(r"<t[dh][^>]*>", " | ", frag)
    text = html.unescape(re.sub(r"<[^>]+>", "", frag))
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for n, url in enumerate(article_urls(), 1):
        module, slug = url.split("/")[-2:]
        page = get(url)
        try:
            body = body_markdown(page)
        except ValueError as exc:
            print(f"BỎ {url}: {exc}", file=sys.stderr)
            continue
        path = OUT / f"{n:02d}_{module}__{slug}.md"
        path.write_text(f"# {title_of(page) or slug}\n\nNguồn: <{url}>\n\n{body}\n", encoding="utf-8")
        print(f"{path}  ({len(body.split())} từ)")


if __name__ == "__main__":
    main()
