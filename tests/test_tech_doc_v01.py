# -*- coding: utf-8 -*-
"""校验《安全生产在线培训平台v0.1技术设计文档.html》的结构完整性与关键内容。"""
import io
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(REPO_ROOT, u"安全生产在线培训平台v0.1技术设计文档.html")


def read_doc():
    with io.open(DOC, "r", encoding="utf-8") as f:
        return f.read()


def test_file_exists_and_size():
    assert os.path.isfile(DOC), u"文档不存在: %s" % DOC
    size = os.path.getsize(DOC)
    assert size > 20000, u"文档过小(%d bytes)" % size


def test_basic_structure():
    html = read_doc()
    assert html.lstrip().lower().startswith("<!doctype html"), u"缺少 DOCTYPE"
    assert "</html>" in html.lower(), u"缺少 </html> 结束标签"
    assert 'charset="UTF-8"' in html or 'charset="utf-8"' in html, u"缺少 UTF-8 声明"
    assert '<body class="mode-doc"' in html, u"缺少 mode-doc 模式标识"
    assert 'data-palette="ink-blue"' in html, u"缺少调色板标识"
    assert "<title>" in html and u"技术设计文档" in html, u"缺少文档标题"


def test_no_external_dependencies():
    html = read_doc()
    ext = re.findall(r'(?:src|href)\s*=\s*["\']https?://[^"\']+', html, re.I)
    assert not ext, u"发现外部资源引用: %r" % ext[:3]
    assert "<script src" not in html.lower(), u"发现外部脚本引用"
    assert "@import" not in html, u"发现 CSS @import"
    assert "<img" not in html.lower(), u"不应包含图片标签（架构图须用内嵌 SVG）"
    assert "cdn" not in html.lower() or "<link" not in html.lower(), u"发现 CDN 链接引用"


def test_no_leftover_placeholders():
    html = read_doc()
    leftovers = re.findall(r"\{(?:[a-z_]{2,30}|[一-龥]{1,20})\}", html)
    assert not leftovers, u"存在未替换的占位符: %r" % leftovers[:5]


def test_scale_analysis_for_400():
    html = read_doc()
    assert u"400" in html, u"缺少 400 人规模测算"
    assert u"容量测算" in html or u"规模评估" in html, u"缺少容量测算章节"
    assert u"QPS" in html, u"缺少心跳写入 QPS 估算"
    assert u"峰值" in html, u"缺少峰值场景估算"


def test_core_technical_decisions_present():
    html = read_doc()
    for kw in [u"FastAPI", u"SQLite", u"WAL", u"SQLAlchemy", u"Uvicorn",
               u"bcrypt", u"原生 H5", u"单进程"]:
        assert kw in html, u"缺少关键选型: %s" % kw


def test_database_design_complete():
    html = read_doc()
    for table in [u"users", u"courses", u"study_records", u"study_sessions", u"export_logs"]:
        assert table in html, u"缺少数据表设计: %s" % table
    assert u"只增不改" in html, u"缺少明细留痕防篡改原则"
    assert u"预留字段" in html, u"缺少升级预留字段说明"


def test_api_versioned():
    html = read_doc()
    assert "/api/v1/" in html, u"API 未版本化（缺少 /api/v1/ 前缀）"
    for api in [u"auth/login", u"study/heartbeat", u"study/confirm",
                u"admin/roster/import", u"admin/export"]:
        assert api in html, u"缺少关键接口: %s" % api


def test_study_engine_design_present():
    html = read_doc()
    assert u"防挂机" in html and u"challenge" in html.lower(), u"缺少防挂机挑战机制"
    assert u"断点" in html, u"缺少断点续学设计"
    assert u"服务端权威" in html, u"缺少服务端权威计时口径"
    assert u"单日" in html and u"上限" in html, u"缺少单日学时上限口径"


def test_upgrade_path_present():
    html = read_doc()
    assert u"升级路径" in html or u"升级成本" in html, u"缺少升级路径章节"
    assert u"PostgreSQL" in html, u"缺少数据库升级路径"
    assert u"LDAP" in html or u"统一身份" in html, u"缺少统一身份升级路径"
    assert u"触发条件" in html, u"缺少升级触发条件表"
    assert u"预估成本" in html, u"缺少升级成本估算"
    assert u"预留" in html, u"缺少低成本预留清单"


def test_deployment_and_backup_present():
    html = read_doc()
    assert u"备份" in html, u"缺少备份策略"
    assert u"服务" in html and (u"NSSM" in html or u"systemd" in html), u"缺少进程托管方案"
    assert u"内网" in html, u"缺少内网部署说明"


def test_config_driven_rules():
    html = read_doc()
    assert u"config.yaml" in html, u"缺少配置文件设计"
    assert u"heartbeat_interval_s" in html, u"缺少心跳间隔配置"
    assert u"challenge" in html, u"缺少防挂机弹窗配置"
    assert u"daily_cap" in html, u"缺少单日上限配置"


def test_semantic_classes_have_styles():
    html = read_doc()
    style = html.split("</style>")[0]
    for cls in ["title", "heading", "paragraph", "list", "card", "table",
                "timeline", "callout", "end_page", "doc-section", "code",
                "toc", "diagram-wrap"]:
        assert ("." + cls) in style, u"样式块缺少语义 class 定义: .%s" % cls


def test_svg_architecture_diagram():
    html = read_doc()
    opens = len(re.findall(r"<svg[\s>]", html, re.I))
    closes = len(re.findall(r"</svg\s*>", html, re.I))
    assert opens >= 1 and opens == closes, u"内嵌 SVG 架构图缺失或标签不配对"
    assert u"架构图" in html or u"分层架构" in html, u"缺少架构图标注"


def test_tags_balanced():
    html = read_doc()
    for tag in ("section", "div", "table", "thead", "tbody", "ol", "ul",
                "li", "aside", "h1", "h2", "h3", "p", "style", "pre", "nav"):
        opens = len(re.findall(r"<%s(?:\s[^>]*)?>" % tag, html, re.I))
        closes = len(re.findall(r"</%s\s*>" % tag, html, re.I))
        assert opens == closes, u"标签 <%s> 不配对: %d 开 / %d 关" % (tag, opens, closes)


def test_milestone_and_risk_present():
    html = read_doc()
    assert u"里程碑" in html, u"缺少开发里程碑"
    assert u"风险" in html and u"对策" in html, u"缺少风险与对策"
    assert u"3 周" in html or u"第 3 周" in html, u"缺少 3 周排期"


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
