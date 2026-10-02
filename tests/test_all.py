"""mssg 单元测试（只用标准库 unittest）。"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mssg import markdown, template
from mssg.frontmatter import split
from mssg.site import Site, new_site


class TestMarkdown(unittest.TestCase):
    def test_heading(self):
        self.assertIn("<h1>标题</h1>", markdown.parse("# 标题"))
        self.assertIn("<h3>小标题</h3>", markdown.parse("### 小标题"))

    def test_paragraph_and_inline(self):
        html = markdown.parse("这是 **粗体** 和 *斜体* 还有 `代码`。")
        self.assertIn("<p>", html)
        self.assertIn("<strong>粗体</strong>", html)
        self.assertIn("<em>斜体</em>", html)
        self.assertIn("<code>代码</code>", html)

    def test_link_image(self):
        html = markdown.parse("[站](https://a.b) ![图](x.png)")
        self.assertIn('<a href="https://a.b">站</a>', html)
        self.assertIn('<img src="x.png" alt="图">', html)

    def test_lists(self):
        html = markdown.parse("- a\n- b\n  - b1\n1. x\n2. y\n")
        self.assertIn("<ul>", html)
        self.assertIn("<ol>", html)
        self.assertIn("<li>b<ul>", html.replace("\n", ""))

    def test_blockquote(self):
        html = markdown.parse("> 引用\n> **加粗**")
        self.assertIn("<blockquote>", html)
        self.assertIn("<strong>加粗</strong>", html)

    def test_fence(self):
        html = markdown.parse("```\nprint(1 < 2)\n```")
        self.assertIn("<pre><code>", html)
        self.assertIn("1 &lt; 2", html)

    def test_table(self):
        html = markdown.parse("| a | b |\n|---|---|\n| 1 | 2 |\n")
        self.assertIn("<table>", html)
        self.assertIn("<th>a</th>", html)
        self.assertIn("<td>2</td>", html)

    def test_hr(self):
        self.assertIn("<hr>", markdown.parse("---"))

    def test_html_escaped(self):
        self.assertIn("&lt;script&gt;", markdown.parse("<script>"))

    def test_unclosed_fence_kept(self):
        # 围栏代码块未闭合：内容不应静默丢失
        html = markdown.parse("```\ncode here")
        self.assertIn("<pre><code>", html)
        self.assertIn("code here", html)

    def test_crlf(self):
        html = markdown.parse("# 标题\r\n\r\n正文\r\n")
        self.assertIn("<h1>标题</h1>", html)
        self.assertNotIn("\r", html)

    def test_empty(self):
        self.assertEqual(markdown.parse(""), "")
        self.assertEqual(markdown.parse("\n\n"), "")

    def test_code_span_protects_markup(self):
        # 行内代码里的标记字符不应被解析
        html = markdown.parse("`**不是粗体**` 和 `*不是斜体*` 和 `[x](y)`")
        self.assertIn("<code>**不是粗体**</code>", html)
        self.assertIn("<code>*不是斜体*</code>", html)
        self.assertIn("<code>[x](y)</code>", html)
        self.assertNotIn("<strong>", html)
        self.assertNotIn("<em>", html)
        self.assertNotIn("<a href", html)

    def test_code_span_escapes_html(self):
        html = markdown.parse("`<b>`")
        self.assertIn("<code>&lt;b&gt;</code>", html)


class TestTemplate(unittest.TestCase):
    def test_var(self):
        self.assertEqual(template.render("Hi {{ name }}!", {"name": "世界"}), "Hi 世界!")

    def test_missing_var(self):
        self.assertEqual(template.render("[{{ nope }}]", {}), "[]")

    def test_dotted(self):
        self.assertEqual(
            template.render("{{ p.title }}", {"p": {"title": "T"}}), "T"
        )

    def test_for(self):
        out = template.render(
            "{% for x in xs %}{{ x }};{% endfor %}", {"xs": [1, 2]}
        )
        self.assertEqual(out, "1;2;")

    def test_for_loop_index(self):
        out = template.render(
            "{% for x in xs %}{{ loop.index }}:{{ x }} {% endfor %}",
            {"xs": ["a", "b"]},
        )
        self.assertEqual(out, "1:a 2:b ")

    def test_if(self):
        tpl = "{% if show %}Y{% else %}N{% endif %}"
        self.assertEqual(template.render(tpl, {"show": True}), "Y")
        self.assertEqual(template.render(tpl, {"show": False}), "N")

    def test_elif(self):
        tpl = "{% if a %}A{% elif b %}B{% else %}C{% endif %}"
        self.assertEqual(template.render(tpl, {"a": 0, "b": 1}), "B")
        self.assertEqual(template.render(tpl, {"a": 0, "b": 0}), "C")

    def test_cond_ops(self):
        tpl = '{% if x == "go" %}GO{% endif %}{% if not y %}NO{% endif %}'
        self.assertEqual(template.render(tpl, {"x": "go", "y": 0}), "GONO")

    def test_comment(self):
        self.assertEqual(template.render("a{# 这是注释 #}b", {}), "ab")
        self.assertEqual(template.render("{# 整行注释 #}", {}), "")
        # 未闭合的注释标记按普通文本保留，不崩溃
        self.assertEqual(template.render("a{# b", {}), "a{# b")

    def test_nested_for(self):
        out = template.render(
            "{% for i in xs %}{% for j in ys %}{{i}}{{j}};{% endfor %}{% endfor %}",
            {"xs": [1, 2], "ys": ["a", "b"]},
        )
        self.assertEqual(out, "1a;1b;2a;2b;")

    def test_deep_nesting_clear_error(self):
        # 病态嵌套：给出明确错误而非裸 RecursionError
        deep = "{% if a %}" * 5000 + "X" + "{% endif %}" * 5000
        with self.assertRaises(ValueError):
            template.render(deep, {"a": 1})

    def test_unclosed_var_kept(self):
        # 未闭合的 {{ 按普通文本保留
        self.assertEqual(template.render("a {{ b", {}), "a {{ b")

    def test_extends(self):
        templates = {
            "base.html": (
                "<title>{% block t %}B{% endblock %}</title>"
                "{% block c %}C{% endblock %}"
            ),
            "page.html": '{% extends "base.html" %}{% block t %}P{% endblock %}',
        }
        out = template.render_template("page.html", {}, templates.get)
        self.assertEqual(out, "<title>P</title>C")

    def test_extends_multilevel(self):
        templates = {
            "a.html": "A{% block x %}ax{% endblock %}",
            "b.html": '{% extends "a.html" %}{% block x %}bx{% endblock %}',
            "c.html": '{% extends "b.html" %}{% block x %}cx{% endblock %}',
        }
        out = template.render_template("c.html", {}, templates.get)
        self.assertEqual(out, "Acx")

    def test_extends_missing_parent(self):
        with self.assertRaises(ValueError):
            template.render_template(
                "x.html", {}, lambda n: '{% extends "nope.html" %}'
            )

    def test_extends_cycle(self):
        def loader(n):
            return (
                '{% extends "b.html" %}'
                if n == "a.html"
                else '{% extends "a.html" %}'
            )

        with self.assertRaises(ValueError):
            template.render_template("a.html", {}, loader)

    def test_extends_not_first_tag(self):
        with self.assertRaises(ValueError):
            template.render("{{ x }}{% extends \"b.html\" %}", {})

    def test_block_without_extends(self):
        # 无继承时 block 按自身内容渲染
        out = template.render("{% block t %}Hi{% endblock %}", {})
        self.assertEqual(out, "Hi")

    def test_elif_else_after_else_error(self):
        with self.assertRaises(ValueError):
            template.render(
                "{% if a %}A{% else %}B{% elif c %}C{% endif %}", {"a": 0}
            )
        with self.assertRaises(ValueError):
            template.render(
                "{% if a %}A{% else %}B{% else %}C{% endif %}", {"a": 0}
            )


class TestFrontMatter(unittest.TestCase):
    def test_split(self):
        meta, body = split("---\ntitle: T\ndate: 2026-01-01\n---\n正文")
        self.assertEqual(meta["title"], "T")
        self.assertEqual(body.strip(), "正文")

    def test_types(self):
        meta, _ = split("---\na: 1\nb: 2.5\nc: true\nd: [x, y]\n---\n")
        self.assertEqual(meta, {"a": 1, "b": 2.5, "c": True, "d": ["x", "y"]})

    def test_no_fm(self):
        meta, body = split("纯正文")
        self.assertEqual(meta, {})
        self.assertEqual(body, "纯正文")

    def test_crlf(self):
        meta, body = split("---\r\ntitle: T\r\n---\r\n正文\r\n")
        self.assertEqual(meta["title"], "T")
        self.assertNotIn("\r", body)

    def test_comment_stripped(self):
        meta, _ = split("---\ntitle: hi # 你好\n---\n")
        self.assertEqual(meta["title"], "hi")
        # 引号内的 # 不是注释
        meta, _ = split('---\ntitle: "a # b"\n---\n')
        self.assertEqual(meta["title"], "a # b")

    def test_quoted_comma_list(self):
        meta, _ = split('---\ntags: ["a,b", c]\n---\n')
        self.assertEqual(meta["tags"], ["a,b", "c"])

    def test_multiline_list(self):
        meta, _ = split("---\ntags:\n  - x\n  - y\n---\n")
        self.assertEqual(meta["tags"], ["x", "y"])


class TestBuild(unittest.TestCase):
    def test_full_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            site = Site(root)
            result = site.build()
            self.assertEqual(result["pages"], 1)
            index = (root / "public" / "index.html").read_text(encoding="utf-8")
            self.assertIn("你好，世界", index)
            page = (root / "public" / "hello.html").read_text(encoding="utf-8")
            self.assertIn("<h1>你好，世界</h1>", page)
            self.assertIn("<strong>mssg</strong>", page)
            css = root / "public" / "style.css"
            self.assertTrue(css.exists())

    def test_incremental(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            site = Site(root)
            first = site.build()
            self.assertTrue(first["rebuilt"])
            second = site.build()
            self.assertFalse(second["rebuilt"])

    def test_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            (root / "content" / "bom.md").write_text(
                "\ufeff---\ntitle: BOM\n---\n正文\n", encoding="utf-8"
            )
            Site(root).build()
            page = (root / "public" / "bom.html").read_text(encoding="utf-8")
            self.assertIn("<title>BOM", page)

    def test_content_index_wins(self):
        # content/index.md 存在时，自动索引不许覆盖它
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            (root / "content" / "index.md").write_text(
                "---\ntitle: 我的首页\n---\n\n# 我的首页\n", encoding="utf-8"
            )
            Site(root).build()
            index = (root / "public" / "index.html").read_text(encoding="utf-8")
            self.assertIn("我的首页", index)
            self.assertNotIn("hello.html", index)

    def test_static_orphan_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            Site(root).build()
            self.assertTrue((root / "public" / "style.css").exists())
            (root / "static" / "style.css").unlink()
            Site(root).build()
            self.assertFalse((root / "public" / "style.css").exists())

    def test_new_site_refuses_nonempty(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "demo")
            os.makedirs(target)
            (Path(target) / "x.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                new_site(target)

    def test_draft_filtered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            result = Site(root).build()
            self.assertEqual(result["pages"], 1)
            self.assertFalse((root / "public" / "draft.html").exists())
            index = (root / "public" / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("草稿示例", index)

    def test_draft_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            result = Site(root).build(include_drafts=True)
            self.assertEqual(result["pages"], 2)
            self.assertTrue((root / "public" / "draft.html").exists())

    def test_draft_stale_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            Site(root).build(include_drafts=True)
            self.assertTrue((root / "public" / "draft.html").exists())
            Site(root).build()
            self.assertFalse((root / "public" / "draft.html").exists())

    def test_tag_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            Site(root).build()
            tag_page = root / "public" / "tags" / "mssg.html"
            self.assertTrue(tag_page.exists())
            html = tag_page.read_text(encoding="utf-8")
            self.assertIn("标签：mssg", html)
            self.assertIn("hello.html", html)

    def test_tag_stale_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            Site(root).build()
            self.assertTrue((root / "public" / "tags" / "mssg.html").exists())
            hello = root / "content" / "hello.md"
            hello.write_text(
                hello.read_text(encoding="utf-8").replace(
                    "tags: [mssg, 示例]\n", ""
                ),
                encoding="utf-8",
            )
            Site(root).build()
            self.assertFalse((root / "public" / "tags" / "mssg.html").exists())

    def test_archive_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            Site(root).build()
            archive = root / "public" / "archive.html"
            self.assertTrue(archive.exists())
            html = archive.read_text(encoding="utf-8")
            self.assertIn("2026-10", html)
            self.assertIn("hello.html", html)

    def test_chinese_tag_url_quoted(self):
        import urllib.parse

        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            Site(root).build()
            tag_page = root / "public" / "tags" / (
                urllib.parse.quote("示例", safe="") + ".html"
            )
            self.assertTrue(tag_page.exists())

    def test_feed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            Site(root).build()
            feed = root / "public" / "feed.xml"
            self.assertTrue(feed.exists())
            xml = feed.read_text(encoding="utf-8")
            self.assertIn("<feed", xml)
            self.assertIn("你好，世界", xml)
            self.assertIn("<updated>2026-10-02T00:00:00Z</updated>", xml)
            # HTML 内容已转义进 XML
            self.assertIn("&lt;h1&gt;", xml)

    def test_feed_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            Site(root).build()
            self.assertTrue((root / "public" / "feed.xml").exists())
            (root / "mssg.toml").write_text(
                '[site]\ntitle = "t"\n[build]\nfeed = false\n',
                encoding="utf-8",
            )
            Site(root).build()
            self.assertFalse((root / "public" / "feed.xml").exists())

    def test_config_change_triggers_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            site = Site(root)
            site.build()
            self.assertFalse(site.build()["rebuilt"])
            toml = root / "mssg.toml"
            toml.write_text(
                toml.read_text(encoding="utf-8").replace("我的小站", "新标题"),
                encoding="utf-8",
            )
            result = Site(root).build()
            self.assertTrue(result["rebuilt"])
            index = (root / "public" / "index.html").read_text(encoding="utf-8")
            self.assertIn("新标题", index)


if __name__ == "__main__":
    unittest.main()
