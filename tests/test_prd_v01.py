# -*- coding: utf-8 -*-
"""校验《安全生产在线培训平台v0.1产品设计文档.html》的结构完整性与规范性。"""
import io
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(REPO_ROOT, u"安全生产在线培训平台v0.1产品设计文档.html")


def read_doc():
    with io.open(DOC, "r", encoding="utf-8") as f:
        return f.read()


def test_file_exists_and_size():
    assert os.path.isfile(DOC), u"文档不存在: %s" % DOC
    size = os.path.getsize(DOC)
    assert size > 5000, u"文档过小(%d bytes)" % size


def test_basic_structure():
    html = read_doc()
    assert html.lstrip().lower().startswith("<!doctype html"), u"缺少 DOCTYPE"
    assert "</html>" in html.lower(), u"缺少 </html> 结束标签"
    assert 'charset="UTF-8"' in html or 'charset="utf-8"' in html, u"缺少 UTF-8 声明"
    assert '<body class="mode-doc"' in html, u"缺少 mode-doc 模式标识"
    assert 'data-palette="ink-blue"' in html, u"缺少调色板标识"
    assert "<title>" in html and "产品设计文档" in html, u"缺少文档标题"


def test_no_external_dependencies():
    html = read_doc()
    ext = re.findall(r'(?:src|href)\s*=\s*["\']https?://[^"\']+', html, re.I)
    assert not ext, u"发现外部资源引用: %r" % ext[:3]
    assert "<script src" not in html.lower(), u"发现外部脚本引用"
    assert "@import" not in html, u"发现 CSS @import"
    assert "<img" not in html.lower(), u"不应包含图片标签（默认无图策略）"


def test_no_leftover_placeholders():
    html = read_doc()
    leftovers = re.findall(r"\{(?:[a-z_]{2,30}|[一-龥]{1,20})\}", html)
    assert not leftovers, u"存在未替换的占位符: %r" % leftovers[:5]


def test_key_content_present():
    html = read_doc()
    for kw in [u"产品设计方向", u"用户与角色", u"主要功能", u"名册", u"课程库",
               u"计时", u"防挂机", u"台账", u"验收标准", u"FastAPI"]:
        assert kw in html, u"缺少关键内容: %s" % kw


def test_semantic_classes_have_styles():
    html = read_doc()
    style = html.split("</style>")[0]
    for cls in ["title", "heading", "paragraph", "list", "card", "table",
                "timeline", "callout", "end_page", "doc-section"]:
        assert ("." + cls) in style, u"样式块缺少语义 class 定义: .%s" % cls


def test_tags_balanced():
    html = read_doc()
    for tag in ("section", "div", "table", "thead", "tbody", "ol", "ul",
                "li", "aside", "h1", "h2", "h3", "p", "style"):
        opens = len(re.findall(r"<%s(?:\s[^>]*)?>" % tag, html, re.I))
        closes = len(re.findall(r"</%s\s*>" % tag, html, re.I))
        assert opens == closes, u"标签 <%s> 不配对: %d 开 / %d 关" % (tag, opens, closes)


def main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print("PASS %s" % t.__name__)
        except AssertionError as e:
            failed += 1
            print("FAIL %s: %s" % (t.__name__, e))
    print("total=%d failed=%d" % (len(tests), failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
