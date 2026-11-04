#!/usr/bin/env python3
"""Build static FAQ HTML pages and FAQPage JSON-LD from docs/faq*.md."""

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
GH = "https://github.com/open-speaker-llm/xiaomi_ai_llm/blob/main/"
SITE = "https://open-speaker-llm.github.io/xiaomi_ai_llm/"

NAV_ZH = """
  <header class="top">
    <div class="wrap">
      <p class="brand"><a href="./">小爱音箱与大模型</a></p>
      <nav>
        <a href="./">首页</a>
        <a href="faq.html" aria-current="page">常见问题</a>
        <a href="install.html">安装</a>
        <a href="models.html">型号</a>
        <a href="en/">English</a>
        <a href="https://github.com/open-speaker-llm/xiaomi_ai_llm">GitHub</a>
      </nav>
    </div>
  </header>
"""

NAV_EN = """
  <header class="top">
    <div class="wrap">
      <p class="brand"><a href="../">xiaomi_ai_llm</a></p>
      <nav>
        <a href="./">Home</a>
        <a href="faq.html" aria-current="page">FAQ</a>
        <a href="../install.html">安装</a>
        <a href="../models.html">型号</a>
        <a href="../faq.html">中文</a>
        <a href="https://github.com/open-speaker-llm/xiaomi_ai_llm">GitHub</a>
      </nav>
    </div>
  </header>
"""


def rewrite_link(url: str, english: bool) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url in ("faq_en.md", "faq.md"):
        return "en/faq.html" if url == "faq_en.md" else ("../faq.html" if english else "faq.html")
    if url.startswith("../"):
        return GH + url[3:]
    return GH + "docs/" + url


def inline(text: str, english: bool) -> str:
    parts = []
    pattern = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))")
    pos = 0
    for match in pattern.finditer(text):
        parts.append(html.escape(text[pos:match.start()]))
        token = match.group(0)
        if token.startswith("**"):
            parts.append("<strong>" + html.escape(token[2:-2]) + "</strong>")
        elif token.startswith("`"):
            parts.append("<code>" + html.escape(token[1:-1]) + "</code>")
        else:
            label, url = re.match(r"\[([^\]]+)\]\(([^)]+)\)", token).groups()
            parts.append(
                '<a href="' + html.escape(rewrite_link(url, english), quote=True) + '">'
                + inline(label, english)
                + "</a>"
            )
        pos = match.end()
    parts.append(html.escape(text[pos:]))
    return "".join(parts)


def plain_inline(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def blocks_to_html(body: str, english: bool) -> str:
    lines = body.strip("\n").split("\n")
    html_parts = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            cells = [
                [cell.strip() for cell in row.strip("|").split("|")]
                for row in rows
                if not re.match(r"^\|\s*-+", row)
            ]
            out = ["<table>"]
            for index, row in enumerate(cells):
                tag = "th" if index == 0 else "td"
                out.append(
                    "<tr>"
                    + "".join(f"<{tag}>{inline(cell, english)}</{tag}>" for cell in row)
                    + "</tr>"
                )
            out.append("</table>")
            html_parts.append("".join(out))
            continue
        if line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append("<li>" + inline(lines[i][2:], english) + "</li>")
                i += 1
            html_parts.append("<ul>" + "".join(items) + "</ul>")
            continue
        para = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith(("- ", "|")):
            para.append(lines[i])
            i += 1
        html_parts.append("<p>" + inline(" ".join(para), english) + "</p>")
    return "\n".join(html_parts)


def plain_blocks(body: str) -> str:
    lines = []
    for raw in body.strip().split("\n"):
        if not raw.strip() or re.match(r"^\|\s*-+", raw):
            continue
        if raw.startswith("|"):
            cells = [cell.strip() for cell in raw.strip("|").split("|")]
            lines.append(" | ".join(plain_inline(cell) for cell in cells))
        elif raw.startswith("- "):
            lines.append(plain_inline(raw[2:]))
        else:
            lines.append(plain_inline(raw))
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse(path: Path):
    text = path.read_text(encoding="utf-8")
    text = re.sub(r'<a id="[^"]+"></a>\n*', "", text)
    intro, *sections = re.split(r"(?m)^## ", text)
    intro = re.sub(r"^# .+\n+", "", intro).strip()
    parsed = []
    for section in sections:
        title, body = section.split("\n", 1)
        parsed.append((title.strip(), body.strip()))
    return intro, parsed


def page(english: bool, intro: str, sections) -> str:
    if english:
        title = "FAQ: Xiaomi XiaoAI speaker LLM, DeepSeek, MDZ-25-DA"
        description = (
            "FAQ for the Xiaomi AI Speaker MDZ-25-DA (S12A): tested model, soldering, "
            "offline use, an always-on computer, native XiaoAI, switching LLMs, web search, "
            "follow-up exit phrases, cost, and the MIT license."
        )
        keywords = "Xiaomi XiaoAI speaker LLM,DeepSeek,MDZ-25-DA,S12A,FAQ"
        canonical = SITE + "en/faq.html"
        lang = "en"
        content_language = "en"
        og_locale = "en_US"
        css = "../site.css"
        nav = NAV_EN
        h1 = "FAQ"
        footer = "MIT for this repo's own code. Not an official Xiaomi project."
        hreflang = f"""
  <link rel="canonical" href="{canonical}">
  <link rel="alternate" hreflang="en" href="{canonical}">
  <link rel="alternate" hreflang="zh-CN" href="{SITE}faq.html">
  <link rel="alternate" hreflang="x-default" href="{SITE}">"""
    else:
        title = "小爱音箱接入 DeepSeek 常见问题（MDZ-25-DA）"
        description = (
            "小爱音箱接入 DeepSeek 的常见问题：支持型号 MDZ-25-DA / S12A、要不要焊接、"
            "是否离线、要不要电脑常驻、原生功能、切换大模型、联网搜索、免唤醒追问怎么结束、费用和 MIT 许可证。"
        )
        keywords = "小爱音箱,小爱音箱接入DeepSeek,常见问题,MDZ-25-DA,S12A,大模型,免唤醒"
        canonical = SITE + "faq.html"
        lang = "zh-CN"
        content_language = "zh-CN"
        og_locale = "zh_CN"
        css = "site.css"
        nav = NAV_ZH
        h1 = "常见问题"
        footer = "自有代码 MIT。不是小米或小爱的官方项目。拆机和写分区有变砖和失去保修的风险。"
        hreflang = f"""
  <link rel="canonical" href="{canonical}">
  <link rel="alternate" hreflang="zh-CN" href="{canonical}">
  <link rel="alternate" hreflang="en" href="{SITE}en/faq.html">
  <link rel="alternate" hreflang="x-default" href="{SITE}">"""

    ids = [
        "models",
        "hardware",
        "offline",
        "always-on",
        "native",
        "llm",
        "followup",
        "compare",
        "cost",
        "license",
    ]
    if len(ids) != len(sections):
        raise SystemExit(f"section count {len(sections)} != {len(ids)}")

    articles = []
    entities = []
    for qid, (qtitle, body) in zip(ids, sections):
        articles.append(
            f'<article class="qa" id="{qid}">\n<h2>{html.escape(qtitle)}</h2>\n'
            f'<div class="a">\n{blocks_to_html(body, english)}\n</div>\n</article>'
        )
        entities.append(
            {
                "@type": "Question",
                "name": qtitle,
                "acceptedAnswer": {"@type": "Answer", "text": plain_blocks(body)},
            }
        )

    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "SoftwareSourceCode",
                "@id": SITE + "#software",
                "name": "xiaomi_ai_llm",
                "codeRepository": "https://github.com/open-speaker-llm/xiaomi_ai_llm",
                "url": SITE,
                "license": "https://opensource.org/licenses/MIT",
                "author": {"@type": "Organization", "name": "open-speaker-llm"},
            },
            {
                "@type": "FAQPage",
                "@id": canonical + "#faq",
                "url": canonical,
                "isPartOf": {"@id": SITE + "#software"},
                "inLanguage": lang,
                "mainEntity": entities,
            },
        ],
    }
    ld = json.dumps(graph, ensure_ascii=False, indent=2)
    intro_html = blocks_to_html(intro, english)
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Language" content="{content_language}">
  <meta name="applicable-device" content="pc,mobile">
  <title>{html.escape(title)}</title>
  <meta name="description" content="{html.escape(description)}">
  <meta name="keywords" content="{html.escape(keywords)}">
  <meta name="robots" content="index,follow">{hreflang}
  <meta property="og:type" content="article">
  <meta property="og:locale" content="{og_locale}">
  <meta property="og:title" content="{html.escape(title)}">
  <meta property="og:description" content="{html.escape(description)}">
  <meta property="og:url" content="{canonical}">
  <meta property="og:image" content="{SITE}assets/bilibili-news-demo.jpg">
  <link rel="stylesheet" href="{css}">
  <script type="application/ld+json">
{ld}
  </script>
</head>
<body>
{nav}
  <main class="wrap">
    <h1>{h1}</h1>
    {intro_html}
    {''.join(articles)}
    <footer><p>{footer}</p></footer>
  </main>
</body>
</html>
"""


def main():
    zh_intro, zh_sections = parse(DOCS / "faq.md")
    en_intro, en_sections = parse(DOCS / "faq_en.md")
    (DOCS / "faq.html").write_text(page(False, zh_intro, zh_sections), encoding="utf-8")
    (DOCS / "en" / "faq.html").write_text(page(True, en_intro, en_sections), encoding="utf-8")
    print("wrote faq.html and en/faq.html")


if __name__ == "__main__":
    main()
