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


if __name__ == "__main__":
    unittest.main()
