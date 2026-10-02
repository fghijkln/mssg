"""mssg 单元测试（只用标准库 unittest）。"""

import argparse
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mssg import cli, markdown, template
from mssg.frontmatter import split
from mssg.site import Site, _is_draft, new_site


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

    def test_link_parens_in_url(self):
        # URL 里的单层括号（如 Wikipedia）不应截断链接
        html = markdown.parse("[w](https://en.wikipedia.org/wiki/X_(Y))")
        self.assertIn('href="https://en.wikipedia.org/wiki/X_(Y)"', html)
        html = markdown.parse("![a](http://e.com/i_(1).png)")
        self.assertIn('src="http://e.com/i_(1).png"', html)
        # 空目标仍不解析
        self.assertNotIn("<a href", markdown.parse("[]()"))

    def test_link_title_skipped(self):
        # "title" 语法要能解析（标题本身不渲染）
        html = markdown.parse('[t](http://e.com/ "ti")')
        self.assertIn('<a href="http://e.com/">t</a>', html)
        html = markdown.parse('![a](x.png "ti")')
        self.assertIn('<img src="x.png" alt="a">', html)

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

    def test_table_pipe_in_code(self):
        # 行内代码里的 | 不能切分单元格
        html = markdown.parse("| `a|b` | c |\n|---|---|\n| 1 | 2 |\n")
        self.assertIn("<th><code>a|b</code></th>", html)
        self.assertIn("<th>c</th>", html)

    def test_table_alignment(self):
        html = markdown.parse("| a | b | c |\n|:---:|---|---:|\n| 1 | 2 | 3 |\n")
        self.assertIn('<th style="text-align:center">a</th>', html)
        self.assertIn("<th>b</th>", html)
        self.assertIn('<th style="text-align:right">c</th>', html)
        self.assertIn('<td style="text-align:center">1</td>', html)

    def test_hr(self):
        self.assertIn("<hr>", markdown.parse("---"))
        # 分隔符之间允许空格（CommonMark 行为）
        self.assertIn("<hr>", markdown.parse("- - -"))
        self.assertIn("<hr>", markdown.parse("* * *"))
        self.assertIn("<hr>", markdown.parse("_ _ _"))

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

    def test_deep_nesting_clear_error(self):
        # 病态嵌套：给出明确错误而非裸 RecursionError
        src = "".join("> " * i + "x\n" for i in range(1200))
        with self.assertRaises(ValueError):
            markdown.parse(src)

    def test_inline_quotes_escaped(self):
        # 引号必须转义，否则会从 alt/src/href 属性里"越狱"出来
        out = markdown.parse('![a"b](http://e.com/)')
        self.assertIn('<img src="http://e.com/" alt="a&quot;b">', out)
        out = markdown.parse('[t](http://e.com/"onmouseover="y)')
        self.assertIn(
            '<a href="http://e.com/&quot;onmouseover=&quot;y">t</a>', out
        )
        out = markdown.parse('`a"b` and **c"d**')
        self.assertIn("<code>a&quot;b</code>", out)
        self.assertIn("<strong>c&quot;d</strong>", out)


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

    def test_method_not_exposed(self):
        # 方法不能通过点号访问，避免泄露 <built-in method …>
        self.assertEqual(template.render("{{ x.strip }}", {"x": "abc"}), "")
        self.assertEqual(
            template.render("{% if x.strip %}T{% else %}F{% endif %}", {"x": "abc"}),
            "F",
        )

    def test_deep_nesting_clear_error(self):
        # 病态嵌套：给出明确错误而非裸 RecursionError
        deep = "{% if a %}" * 5000 + "X" + "{% endif %}" * 5000
        with self.assertRaises(ValueError):
            template.render(deep, {"a": 1})

    def test_unclosed_var_kept(self):
        # 未闭合的 {{ 按普通文本保留
        self.assertEqual(template.render("a {{ b", {}), "a {{ b")

    def test_unclosed_markers_consistent(self):
        # 未闭合的标记无论在行首还是行中，都按普通文本保留（行为一致）
        self.assertEqual(template.render("{{ x }", {"x": 1}), "{{ x }")
        self.assertEqual(template.render("a{{ x }", {"x": 1}), "a{{ x }")
        self.assertEqual(template.render("{# b", {}), "{# b")
        self.assertEqual(template.render("a{# b", {}), "a{# b")
        self.assertEqual(template.render("{% if x", {}), "{% if x")
        self.assertEqual(template.render("a{% if x", {}), "a{% if x")

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

    def test_include(self):
        templates = {
            "page.html": 'A{% include "part.html" %}B',
            "part.html": "P{{ x }}",
        }
        out = template.render_template("page.html", {"x": 1}, templates.get)
        self.assertEqual(out, "AP1B")

    def test_include_missing(self):
        with self.assertRaises(ValueError):
            template.render('{% include "nope.html" %}', {}, {}.get)

    def test_include_needs_loader(self):
        with self.assertRaises(ValueError):
            template.render('{% include "p.html" %}', {})

    def test_include_cycle(self):
        def loader(n):
            return (
                '{% include "b.html" %}'
                if n == "a.html"
                else '{% include "a.html" %}'
            )

        with self.assertRaises(ValueError):
            template.render_template("a.html", {}, loader)

    def test_include_complex_cycle_and_diamond(self):
        # 三元环报出完整链条
        t = {
            "a": 'A{% include "b" %}',
            "b": 'B{% include "c" %}',
            "c": 'C{% include "a" %}',
        }
        with self.assertRaises(ValueError) as cm:
            template.render_template("a", {}, t.get)
        self.assertIn("include 循环", str(cm.exception))
        # 菱形（非循环）正常渲染
        t3 = {
            "a": 'A{% include "b" %}{% include "c" %}',
            "b": 'B{% include "d" %}',
            "c": 'C{% include "d" %}',
            "d": "D",
        }
        self.assertEqual(template.render_template("a", {}, t3.get), "ABDCD")

    def test_include_with_extends_error(self):
        templates = {
            "page.html": '{% include "child.html" %}',
            "child.html": '{% extends "base.html" %}',
            "base.html": "B",
        }
        with self.assertRaises(ValueError):
            template.render_template("page.html", {}, templates.get)

    def test_extends_three_levels(self):
        # 三级继承：每级的 block 覆盖都生效
        templates = {
            "base": "B[{% block a %}A{% endblock %}][{% block b %}BaseB{% endblock %}]",
            "mid": '{% extends "base" %}{% block a %}MidA{% endblock %}',
            "leaf": '{% extends "mid" %}{% block b %}LeafB{% endblock %}',
        }
        out = template.render_template("leaf", {}, templates.get)
        self.assertEqual(out, "B[MidA][LeafB]")

    def test_include_inside_block(self):
        # block 里的 include 在渲染时展开，能用当前上下文
        templates = {
            "base": "X{% block c %}base-c{% endblock %}Y",
            "child": '{% extends "base" %}{% block c %}[{% include "p" %}]{% endblock %}',
            "p": "P{{ v }}",
        }
        out = template.render_template("child", {"v": 1}, templates.get)
        self.assertEqual(out, "X[P1]Y")

    def test_no_hang_battery(self):
        """防挂起电池：棘手模板组合在子进程中限时渲染。

        若解析器某天又出现无限循环（如漏写 pos += 1），
        这个测试会明确失败，而不是让整个套件卡死。
        """
        import subprocess

        repo = str(Path(__file__).resolve().parent.parent)
        lines = [
            "import sys",
            "sys.path.insert(0, %r)" % repo,
            "from mssg import template",
            "templates = {",
            "    'a': 'A{% include \"b\" %}',",
            "    'b': 'B{% for x in xs %}{{ x }}{% endfor %}',",
            "    'c': '{% if a %}{% include \"b\" %}{% endif %}',",
            "    'd': '{% block t %}{% include \"b\" %}{% endblock %}',",
            "    'e': '{% for i in xs %}{% include \"f\" %}{% endfor %}',",
            "    'f': '{% for j in ys %}{{ j }}{% endfor %}',",
            "    'g': '{% include \"h\" %}',",
            "    'h': '{% include \"g\" %}',",
            "}",
            "ctx = {'xs': [1, 2], 'ys': ['a'], 'a': True}",
            "for name in 'abcdef':",
            "    template.render_template(name, ctx, templates.get)",
            "try:",
            "    template.render_template('g', ctx, templates.get)",
            "except ValueError:",
            "    pass",
            "else:",
            "    raise SystemExit('cycle should raise')",
            "print('BATTERY-OK')",
        ]
        proc = subprocess.run(
            [sys.executable, "-c", "\n".join(lines)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        self.assertIn("BATTERY-OK", proc.stdout)


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
        # # 在值开头也是注释
        meta, _ = split("---\nkey: # 纯注释\n---\n")
        self.assertEqual(meta["key"], "")
        # # 前无空白则不是注释
        meta, _ = split("---\nkey: a#b\n---\n")
        self.assertEqual(meta["key"], "a#b")

    def test_list_comment_only_item_dropped(self):
        # 整项都是注释的行内列表项应被丢弃
        meta, _ = split("---\ntags: [#x, a]\n---\n")
        self.assertEqual(meta["tags"], ["a"])

    def test_quoted_comma_list(self):
        meta, _ = split('---\ntags: ["a,b", c]\n---\n')
        self.assertEqual(meta["tags"], ["a,b", "c"])

    def test_not_front_matter_without_keys(self):
        # --- 块里没有任何有效键：不是 front matter，内容不能被吞掉
        meta, body = split("---\njust some text\n---\n\n正文\n")
        self.assertEqual(meta, {})
        self.assertIn("just some text", body)
        self.assertIn("正文", body)
        # 纯空的 --- 块仍是合法的空 front matter
        meta, body = split("---\n---\n正文\n")
        self.assertEqual(meta, {})
        self.assertEqual(body, "正文\n")

    def test_multiline_list(self):
        meta, _ = split("---\ntags:\n  - x\n  - y\n---\n")
        self.assertEqual(meta["tags"], ["x", "y"])

    def test_multiline_list_comment_stripped(self):
        # 多行列表项的行尾注释也要剥离，与行内列表保持一致
        meta, _ = split("---\ntags:\n  - a # 注释\n  - 'b # c'\n---\n")
        self.assertEqual(meta["tags"], ["a", "b # c"])


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

    def test_deleted_page_cleanup(self):
        # 删除源 Markdown 后：输出 HTML 被清理，索引不再收录，且触发重建
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            (root / "content" / "gone.md").write_text(
                "---\ntitle: 消失\ndate: 2026-01-01\n---\n\nbye\n",
                encoding="utf-8",
            )
            Site(root).build()
            self.assertTrue((root / "public" / "gone.html").exists())
            index = (root / "public" / "index.html").read_text(encoding="utf-8")
            self.assertIn("gone.html", index)
            (root / "content" / "gone.md").unlink()
            result = Site(root).build()
            self.assertTrue(result["rebuilt"])
            self.assertFalse((root / "public" / "gone.html").exists())
            index = (root / "public" / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("gone.html", index)
            sm = (root / "public" / "sitemap.xml").read_text(encoding="utf-8")
            self.assertNotIn("gone.html", sm)

    def test_feed_escaping_levels(self):
        # feed 里 HTML 内容应双重转义：XML 解析后得到合法的单重转义 HTML
        import xml.etree.ElementTree as ET

        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            (root / "content" / "a.md").write_text(
                "---\ntitle: A&B\ndate: 2026-01-01\n---\n\nFish & Chips\n",
                encoding="utf-8",
            )
            Site(root).build()
            feed = (root / "public" / "feed.xml").read_text(encoding="utf-8")
            self.assertIn("Fish &amp;amp; Chips", feed)
            t = ET.fromstring(feed)
            ns = {"a": "http://www.w3.org/2005/Atom"}
            entries = t.findall("a:entry", ns)
            mine = [
                e for e in entries if e.find("a:title", ns).text == "A&B"
            ][0]
            self.assertEqual(
                mine.find("a:content", ns).text, "<p>Fish &amp; Chips</p>"
            )

    def test_base_url_absolute_links(self):
        # base_url 末尾斜杠不应导致双斜杠
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            toml = (root / "mssg.toml").read_text(encoding="utf-8")
            (root / "mssg.toml").write_text(
                toml.replace('base_url = ""', 'base_url = "https://example.com/blog/"'),
                encoding="utf-8",
            )
            Site(root).build()
            feed = (root / "public" / "feed.xml").read_text(encoding="utf-8")
            self.assertIn("https://example.com/blog/feed.xml", feed)
            self.assertNotIn("blog//", feed)
            sm = (root / "public" / "sitemap.xml").read_text(encoding="utf-8")
            self.assertIn("<loc>https://example.com/blog/index.html</loc>", sm)

    def test_sitemap_includes_archive_and_tags(self):        # 归档页与标签页也是可访问的 HTML，应计入 sitemap
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            Site(root).build()
            sm = (root / "public" / "sitemap.xml").read_text(encoding="utf-8")
            self.assertIn("<loc>/archive.html</loc>", sm)
            self.assertIn("<loc>/tags/mssg.html</loc>", sm)

    def test_sitemap_no_duplicate_index(self):        # content/index.md 存在时，sitemap 里 index.html 只出现一次
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            (root / "content" / "index.md").write_text(
                "---\ntitle: 首页\n---\n\n# 首页\n", encoding="utf-8"
            )
            Site(root).build()
            sm = (root / "public" / "sitemap.xml").read_text(encoding="utf-8")
            self.assertEqual(sm.count("<loc>/index.html</loc>"), 1)

    def _make_paged_site(self, tmp, n=5, per_page=2):
        root = new_site(os.path.join(tmp, "demo"))
        for i in range(n):
            (root / "content" / ("p%d.md" % i)).write_text(
                "---\ntitle: 文章%d\ndate: 2026-09-%02d\ntags: [t]\n---\n\n正文%d\n"
                % (i, i + 1, i),
                encoding="utf-8",
            )
        toml = (root / "mssg.toml").read_text(encoding="utf-8")
        (root / "mssg.toml").write_text(
            toml.replace("# per_page = 5", "per_page = %d" % per_page),
            encoding="utf-8",
        )
        return root

    def test_pagination_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_paged_site(tmp, n=5, per_page=2)
            Site(root).build()
            # hello + 5 篇 = 6 页内容 → 3 页
            self.assertTrue((root / "public" / "page" / "2.html").exists())
            self.assertTrue((root / "public" / "page" / "3.html").exists())
            self.assertFalse((root / "public" / "page" / "4.html").exists())
            index = (root / "public" / "index.html").read_text(encoding="utf-8")
            self.assertIn('href="/page/2.html"', index)
            self.assertIn("1 / 3", index)
            self.assertNotIn("上一页", index)
            p3 = (root / "public" / "page" / "3.html").read_text(encoding="utf-8")
            self.assertIn('href="/page/2.html"', p3)  # 上一页
            self.assertNotIn("下一页", p3)
            sm = (root / "public" / "sitemap.xml").read_text(encoding="utf-8")
            self.assertIn("<loc>/page/2.html</loc>", sm)

    def test_pagination_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_paged_site(tmp, n=3, per_page=2)
            Site(root).build()
            t2 = root / "public" / "tags" / "t" / "2.html"
            self.assertTrue(t2.exists())
            html = t2.read_text(encoding="utf-8")
            self.assertIn('href="/tags/t.html"', html)  # 上一页回到第一页
            self.assertIn("2 / 2", html)

    def test_content_index_added_later_cleans_pagination(self):
        # 先有分页，后加 content/index.md：分页残留清理，但自定义首页保留
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_paged_site(tmp, n=4, per_page=2)
            Site(root).build()
            self.assertTrue((root / "public" / "page" / "2.html").exists())
            (root / "content" / "index.md").write_text(
                "---\ntitle: 首页\n---\n\n# 首页\n", encoding="utf-8"
            )
            Site(root).build()
            index = (root / "public" / "index.html").read_text(encoding="utf-8")
            self.assertIn("首页", index)
            self.assertFalse((root / "public" / "page" / "2.html").exists())
            sm = (root / "public" / "sitemap.xml").read_text(encoding="utf-8")
            self.assertNotIn("/page/2.html", sm)
            self.assertEqual(sm.count("<loc>/index.html</loc>"), 1)

    def test_template_rename_triggers_rebuild(self):
        # 模板重命名（内容不变、排序位置不变）也要触发重建
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            Site(root).build()
            self.assertFalse(Site(root).build()["rebuilt"])
            (root / "templates" / "page.html").rename(
                root / "templates" / "page2.html"
            )
            self.assertTrue(Site(root).build()["rebuilt"])

    def test_pagination_per_page_change_cleans(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_paged_site(tmp, n=5, per_page=2)
            Site(root).build()
            self.assertTrue((root / "public" / "page" / "3.html").exists())
            toml = (root / "mssg.toml").read_text(encoding="utf-8")
            (root / "mssg.toml").write_text(
                toml.replace("per_page = 2", "per_page = 10"), encoding="utf-8"
            )
            Site(root).build()
            self.assertFalse((root / "public" / "page" / "2.html").exists())
            self.assertFalse((root / "public" / "page" / "3.html").exists())

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

    def test_sitemap(self):
        import xml.dom.minidom

        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            Site(root).build()
            sm = root / "public" / "sitemap.xml"
            self.assertTrue(sm.exists())
            xml.dom.minidom.parse(str(sm))  # 合法 XML
            text = sm.read_text(encoding="utf-8")
            self.assertIn("hello.html", text)
            self.assertIn("<lastmod>2026-10-02</lastmod>", text)

    def test_build_reports_bad_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            (root / "content" / "bad.md").write_text(
                "".join("> " * i + "x\n" for i in range(1200)),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError) as cm:
                Site(root).build()
            self.assertIn("bad.md", str(cm.exception))


class TestCLI(unittest.TestCase):
    def _run_build(self, root) -> int:
        old = os.getcwd()
        os.chdir(root)
        try:
            args = argparse.Namespace(
                config="mssg.toml", force=False, drafts=False
            )
            return cli._cmd_build(args)
        finally:
            os.chdir(old)

    def test_build_error_friendly(self):
        # 模板写坏时 CLI 打印一行友好错误并返回 1，不抛 traceback
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            (root / "templates" / "page.html").write_text(
                "{% if x %}oops", encoding="utf-8"
            )
            self.assertEqual(self._run_build(root), 1)

    def test_build_ok_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            self.assertEqual(self._run_build(root), 0)

    def test_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            Site(root).build()
            self.assertTrue((root / "public").exists())
            old = os.getcwd()
            os.chdir(root)
            try:
                self.assertEqual(
                    cli._cmd_clean(argparse.Namespace(config="mssg.toml")), 0
                )
            finally:
                os.chdir(old)
            self.assertFalse((root / "public").exists())

    def test_new_rejects_existing_file(self):
        # new 的目标是已存在文件时，应报明确错误而非 traceback
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "myfile")
            Path(f).write_text("x", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                new_site(f)

    def test_clean_refuses_site_root(self):
        # output_dir 指向站点根时拒绝清空，防止误删
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            with open(root / "mssg.toml", "a", encoding="utf-8") as f:
                f.write('output_dir = "."\n')
            old = os.getcwd()
            os.chdir(root)
            try:
                self.assertEqual(
                    cli._cmd_clean(argparse.Namespace(config="mssg.toml")), 1
                )
            finally:
                os.chdir(old)
            self.assertTrue((root / "content").exists())

    def test_is_draft_types(self):
        # 各类型 draft 值的语义一致：真值即草稿
        self.assertTrue(_is_draft(True))
        self.assertTrue(_is_draft("true"))
        self.assertTrue(_is_draft("yes"))
        self.assertTrue(_is_draft("1"))
        self.assertTrue(_is_draft(1))
        self.assertFalse(_is_draft(False))
        self.assertFalse(_is_draft("false"))
        self.assertFalse(_is_draft(0))
        self.assertFalse(_is_draft(None))

    def test_build_reloads_config(self):        # 同一个 Site 对象：改 mssg.toml 后再次 build 要用新配置
        # （serve 的文件监听就靠这个）
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            site = Site(root)
            site.build()
            index = (root / "public" / "index.html").read_text(encoding="utf-8")
            self.assertIn("我的小站", index)
            toml = (root / "mssg.toml").read_text(encoding="utf-8")
            (root / "mssg.toml").write_text(
                toml.replace('title = "我的小站"', 'title = "新标题"'),
                encoding="utf-8",
            )
            site.build()
            index = (root / "public" / "index.html").read_text(encoding="utf-8")
            self.assertIn("新标题", index)


if __name__ == "__main__":
    unittest.main()
