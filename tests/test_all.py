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
    """基于 Python-Markdown：完整 Markdown（含表格/脚注/代码高亮/TOC 锚点）。"""

    def test_heading(self):
        # toc 扩展给所有级别标题加锚点 id
        self.assertIn('<h1 id="标题">标题</h1>', markdown.parse("# 标题"))
        self.assertIn('<h3 id="小标题">小标题</h3>', markdown.parse("### 小标题"))

    def test_paragraph_and_inline(self):
        html = markdown.parse("这是 **粗体** 和 *斜体* 还有 `代码`。")
        self.assertIn("<p>", html)
        self.assertIn("<strong>粗体</strong>", html)
        self.assertIn("<em>斜体</em>", html)
        self.assertIn("<code>代码</code>", html)

    def test_link_image(self):
        html = markdown.parse("[站](https://a.b) ![图](x.png)")
        self.assertIn('<a href="https://a.b">站</a>', html)
        self.assertIn('alt="图"', html)
        self.assertIn('src="x.png"', html)

    def test_link_parens_in_url(self):
        # URL 里的单层括号（如 Wikipedia）不应截断链接
        html = markdown.parse("[w](https://en.wikipedia.org/wiki/X_(Y))")
        self.assertIn('href="https://en.wikipedia.org/wiki/X_(Y)"', html)
        html = markdown.parse("![a](http://e.com/i_(1).png)")
        self.assertIn('src="http://e.com/i_(1).png"', html)
        # 空目标：标准行为是生成空 href 链接
        self.assertIn('<a href="">', markdown.parse("[]()"))

    def test_link_title(self):
        # title 属性正常渲染为 title="..."
        html = markdown.parse('[t](http://e.com/ "ti")')
        self.assertIn('<a href="http://e.com/" title="ti">t</a>', html)
        html = markdown.parse('![a](x.png "ti")')
        self.assertIn('title="ti"', html)

    def test_lists(self):
        html = markdown.parse("- a\n- b\n\n    - b1\n")
        self.assertIn("<ul>", html)
        compact = html.replace("\n", "").replace(" ", "")
        self.assertIn("<li><p>b</p><ul><li>b1</li></ul></li>", compact)
        html = markdown.parse("1. x\n2. y\n")
        self.assertIn("<ol>", html)
        self.assertIn("<li>x</li>", html.replace("\n", ""))

    def test_blockquote(self):
        html = markdown.parse("> 引用\n> **加粗**")
        self.assertIn("<blockquote>", html)
        self.assertIn("<strong>加粗</strong>", html)

    def test_fence_highlight(self):
        # codehilite + Pygments：代码高亮
        html = markdown.parse("```python\nprint(1 < 2)\n```")
        self.assertIn('class="codehilite"', html)
        self.assertIn("&lt;", html)  # < 被转义（在高亮 span 内）
        self.assertIn("<span", html)  # 有高亮 span

    def test_fence_no_lang(self):
        html = markdown.parse("```\nplain\n```")
        self.assertIn('class="codehilite"', html)

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
        self.assertIn('style="text-align: center;"', html)
        self.assertIn('style="text-align: right;"', html)

    def test_hr(self):
        self.assertIn("<hr", markdown.parse("---"))
        self.assertIn("<hr", markdown.parse("- - -"))
        self.assertIn("<hr", markdown.parse("* * *"))

    def test_raw_html_passthrough(self):
        # 标准 Markdown 语义：行内 HTML 原样通过（<!--more--> 等依赖它）
        html = markdown.parse("a <!--more--> b")
        self.assertIn("<!--more-->", html)

    def test_unclosed_fence_literal(self):
        # 围栏未闭合：Python-Markdown 按字面输出，不静默吞内容
        html = markdown.parse("```\ncode here")
        self.assertIn("code here", html)

    def test_crlf(self):
        html = markdown.parse("# 标题\r\n\r\n正文\r\n")
        self.assertIn("标题", html)
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

    def test_footnotes(self):
        # extra 扩展：脚注
        html = markdown.parse("脚注[^1]\n\n[^1]: 内容\n")
        self.assertIn('class="footnote-ref"', html)
        self.assertIn("内容", html)

    def test_deep_nesting_no_crash(self):
        # 病态嵌套：Python-Markdown 能处理完，不挂起不崩溃
        src = "".join("> " * i + "x\n" for i in range(200))
        html = markdown.parse(src)
        self.assertIn("<blockquote>", html)

    def test_inline_quotes_escaped(self):
        # 引号必须转义，否则会从 alt/src/href 属性里"越狱"出来
        out = markdown.parse('![a"b](http://e.com/)')
        self.assertIn('alt="a&quot;b"', out)
        out = markdown.parse('`a"b` and **c"d**')
        # 代码 span 里 " 无需转义（已在 code 标签内，安全）
        self.assertIn("<code>a\"b</code>", out)
        self.assertIn("<strong>c\"d</strong>", out)

    def test_toc_extract(self):
        toc = markdown.extract_toc("# 主\n## 第二章\n### 2.1 节\n")
        self.assertEqual(len(toc), 2)
        self.assertEqual(toc[0], {"level": 2, "text": "第二章", "id": "第二章"})
        self.assertEqual(toc[1]["level"], 3)
        self.assertEqual(toc[1]["id"], "21-节")

    def test_slugify(self):
        self.assertEqual(markdown.slugify("Hello World"), "hello-world")
        self.assertEqual(markdown.slugify("中文 标题"), "中文-标题")
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
        # 未闭合的注释标记：Jinja2 报语法错误（明确失败优于静默保留）
        with self.assertRaises(ValueError):
            template.render("a{# b", {})

    def test_nested_for(self):
        out = template.render(
            "{% for i in xs %}{% for j in ys %}{{i}}{{j}};{% endfor %}{% endfor %}",
            {"xs": [1, 2], "ys": ["a", "b"]},
        )
        self.assertEqual(out, "1a;1b;2a;2b;")

    def test_method_not_called(self):
        # 点号取到方法时 Jinja2 只渲染 repr，绝不调用它
        class Obj:
            def boom(self):
                return "CALLED"

        out = template.render("{{ o.boom }}", {"o": Obj()})
        self.assertNotIn("CALLED", out)

    def test_deep_nesting_clear_error(self):
        # 病态嵌套：给出明确错误而非裸 RecursionError
        deep = "{% if a %}" * 5000 + "X" + "{% endif %}" * 5000
        with self.assertRaises(ValueError):
            template.render(deep, {"a": 1})

    def test_unclosed_markers_error(self):
        # 未闭合的标记统一报 ValueError（Jinja2 严格模式）
        for src in ("a {{ b", "{{ x }", "a{{ x }", "{# b",
                    "a{# b", "{% if x", "a{% if x"):
            with self.assertRaises(ValueError, msg=src):
                template.render(src, {"x": 1})

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
        self.assertIn("循环", str(cm.exception))
        # 菱形（非循环）正常渲染
        t3 = {
            "a": 'A{% include "b" %}{% include "c" %}',
            "b": 'B{% include "d" %}',
            "c": 'C{% include "d" %}',
            "d": "D",
        }
        self.assertEqual(template.render_template("a", {}, t3.get), "ABDCD")

    def test_include_with_extends(self):
        # Jinja2 允许被 include 的模板使用 extends（旧自研引擎曾禁止）
        templates = {
            "page.html": '{% include "child.html" %}',
            "child.html": '{% extends "base.html" %}{% block b %}C{% endblock %}',
            "base.html": "B{% block b %}{% endblock %}",
        }
        out = template.render_template("page.html", {}, templates)
        self.assertEqual(out, "BC")

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
        # # 在值开头是 YAML 注释 → 值为 None（标准 YAML 语义）
        meta, _ = split("---\nkey: # 纯注释\n---\n")
        self.assertIsNone(meta["key"])
        # # 前无空白则不是注释
        meta, _ = split("---\nkey: a#b\n---\n")
        self.assertEqual(meta["key"], "a#b")

    def test_list_comment_only_item_dropped(self):
        # 行内列表里写注释是非法的 YAML → 整个 front matter 视为无效
        meta, _ = split("---\ntags: [#x, a]\n---\n")
        self.assertEqual(meta, {})

    def test_unicode_key(self):
        # 非 ASCII 键名（如中文）也应解析
        meta, _ = split("---\n标题: 你好\ntitle: T\n---\n")
        self.assertEqual(meta["标题"], "你好")
        self.assertEqual(meta["title"], "T")

    def test_title_strips_inline_markdown(self):
        # 从正文标题提取的 title 应去掉 ** 等行内标记
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            (root / "content" / "a.md").write_text(
                "---\ndate: 2026-01-01\n---\n\n# Hello **bold** and `code`\n\nx\n",
                encoding="utf-8",
            )
            Site(root).build()
            html = (root / "public" / "a.html").read_text(encoding="utf-8")
            self.assertIn("<title>Hello bold and code -", html)
            self.assertNotIn("**bold**", html)

    def test_entities_preserved(self):
        # 已有 HTML 实体不被双重转义；裸 & 仍转义
        self.assertEqual(markdown.parse("A &amp; B"), "<p>A &amp; B</p>")
        self.assertEqual(markdown.parse("A & B"), "<p>A &amp; B</p>")
        self.assertIn("&copy;", markdown.parse("x &copy; y"))

    def test_helpers_unit(self):
        # 纯函数直接单元测试
        from mssg.site import _clean_title, _paginate, _atom_date, _tag_slug

        self.assertEqual(_clean_title("**b** and `c`"), "b and c")
        self.assertEqual(_clean_title("[t](http://x)"), "t")
        self.assertEqual(_paginate([1, 2, 3], 2), [[1, 2], [3]])
        self.assertEqual(_paginate([1, 2], 0), [[1, 2]])
        self.assertEqual(_atom_date("2026-01-02"), "2026-01-02T00:00:00Z")
        self.assertEqual(_tag_slug("a/b"), "a-b")
        self.assertEqual(_tag_slug("中文"), "中文")
        self.assertEqual(_tag_slug(""), "tag")

    def test_empty_date_falls_back_to_mtime(self):
        # date: 留空时应回退到文件 mtime，而不是显示 []
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            (root / "content" / "a.md").write_text(
                "---\ntitle: A\ndate:\n---\n\nx\n", encoding="utf-8"
            )
            Site(root).build()
            html = (root / "public" / "archive.html").read_text(encoding="utf-8")
            self.assertNotIn("<h2>[]</h2>", html)

    def test_scalar_tag(self):
        # tags 写成标量（如 tags: 5）不应崩构建，视为单个标签
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            (root / "content" / "a.md").write_text(
                "---\ntitle: A\ndate: 2026-01-01\ntags: 5\n---\n\nx\n",
                encoding="utf-8",
            )
            Site(root).build()
            self.assertTrue((root / "public" / "tags" / "5.html").exists())

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
            self.assertEqual(result["pages"], 4)  # hello + about + products + contact
            index = (root / "public" / "index.html").read_text(encoding="utf-8")
            self.assertIn("你好，世界", index)
            page = (root / "public" / "hello.html").read_text(encoding="utf-8")
            self.assertIn('<h1 id="你好世界">你好，世界</h1>', page)
            self.assertIn("<strong>mssg</strong>", page)
            css = root / "public" / "style.css"
            self.assertTrue(css.exists())

    def test_kitchen_sink(self):
        # 综合：分页+中文标签+草稿+实体+表格+自定义首页，一次构建全验证
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            toml = (root / "mssg.toml").read_text(encoding="utf-8")
            (root / "mssg.toml").write_text(
                toml.replace("# per_page = 5", "per_page = 1"), encoding="utf-8"
            )
            for i in range(3):
                (root / "content" / ("p%d.md" % i)).write_text(
                    "---\ntitle: 文章%d\ndate: 2026-01-0%d\ntags: [中文, t]\n---\n\n"
                    "# 标题%d\n\nA &amp; B\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
                    % (i, i + 1, i),
                    encoding="utf-8",
                )
            (root / "content" / "d.md").write_text(
                "---\ntitle: 草稿\ndate: 2026-01-01\ndraft: true\n---\n\nx\n",
                encoding="utf-8",
            )
            (root / "content" / "index.md").write_text(
                "---\ntitle: 首页\ndate: 2026-01-10\n---\n\n# 欢迎\n", encoding="utf-8"
            )
            result = Site(root).build()
            # 3 文章 + 4 示例(hello/about/products/contact) + 1 首页 = 8（草稿排除）
            self.assertEqual(result["pages"], 8)
            pub = root / "public"
            # 自定义首页
            self.assertIn("欢迎", (pub / "index.html").read_text(encoding="utf-8"))
            # 中文标签页可访问
            self.assertTrue((pub / "tags" / "中文.html").exists())
            # 草稿无残留
            all_text = " ".join(
                p.read_text(encoding="utf-8") for p in pub.rglob("*.html")
            )
            self.assertNotIn("草稿", all_text)
            # 实体不双重转义
            p0 = (pub / "p0.html").read_text(encoding="utf-8")
            self.assertNotIn("&amp;amp;", p0)
            # 表格正常
            self.assertIn("<table>", p0)
            # feed/sitemap/archive 齐全
            for f in ["feed.xml", "sitemap.xml", "archive.html"]:
                self.assertTrue((pub / f).exists())

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
            # hello/about/products/contact + 5 篇 = 9 页内容 → 5 页
            self.assertTrue((root / "public" / "page" / "2.html").exists())
            self.assertTrue((root / "public" / "page" / "5.html").exists())
            self.assertFalse((root / "public" / "page" / "6.html").exists())
            index = (root / "public" / "index.html").read_text(encoding="utf-8")
            self.assertIn('href="/page/2.html"', index)
            self.assertIn("1 / 5", index)
            self.assertNotIn("上一页", index)
            p5 = (root / "public" / "page" / "5.html").read_text(encoding="utf-8")
            self.assertIn('href="/page/4.html"', p5)  # 上一页
            self.assertNotIn("下一页", p5)
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
            self.assertEqual(result["pages"], 4)
            self.assertFalse((root / "public" / "draft.html").exists())
            index = (root / "public" / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("草稿示例", index)

    def test_draft_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            result = Site(root).build(include_drafts=True)
            self.assertEqual(result["pages"], 5)
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

    def test_chinese_tag_url(self):
        # 中文标签用原文做文件名（不用百分号编码，否则 HTTP 服务时 404）
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            Site(root).build()
            tag_page = root / "public" / "tags" / "示例.html"
            self.assertTrue(tag_page.exists())

    def test_tag_slug_collision(self):
        # 不同标签撞 slug 时加后缀区分
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            (root / "content" / "a.md").write_text(
                "---\ntitle: A\ndate: 2026-01-01\ntags: [a/b]\n---\n\nx\n",
                encoding="utf-8",
            )
            (root / "content" / "b.md").write_text(
                "---\ntitle: B\ndate: 2026-01-02\ntags: [a-b]\n---\n\nx\n",
                encoding="utf-8",
            )
            Site(root).build()
            self.assertTrue((root / "public" / "tags" / "a-b.html").exists())
            self.assertTrue((root / "public" / "tags" / "a-b-2.html").exists())

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
            self.assertIn("&lt;h1", xml)

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
                toml.read_text(encoding="utf-8").replace("星尘科技", "新标题"),
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
        # 模板语法错误：构建报错必须带上出问题的页面文件名
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            (root / "content" / "bad.md").write_text(
                "---\ntitle: 坏页\ntemplate: broken.html\n---\n\n内容\n",
                encoding="utf-8",
            )
            (root / "templates" / "broken.html").write_text(
                "{% if x %}未闭合", encoding="utf-8"
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

    def test_new_post_dispatch(self):
        # mssg new post <slug> 新建文章；mssg new <name> 建站（兼容旧行为）
        with tempfile.TemporaryDirectory() as tmp:
            old = os.getcwd()
            try:
                os.chdir(tmp)
                os.mkdir("site1")
                os.chdir("site1")
                Path("mssg.toml").write_text("[site]", encoding="utf-8")
                args = argparse.Namespace(
                    target="post", slug="hello", title="你好", config="mssg.toml"
                )
                self.assertEqual(cli._cmd_new_dispatch(args), 0)
                self.assertTrue(Path("content/hello.md").is_file())
                text = Path("content/hello.md").read_text(encoding="utf-8")
                self.assertIn("title: 你好", text)
                # 缺 slug 时报错
                args2 = argparse.Namespace(
                    target="post", slug=None, title="", config="mssg.toml"
                )
                self.assertEqual(cli._cmd_new_dispatch(args2), 1)
                # new <name> 仍是建站
                os.chdir(tmp)
                self.assertEqual(
                    cli._cmd_new_dispatch(argparse.Namespace(target="newsite")), 0
                )
                self.assertTrue((Path(tmp) / "newsite" / "mssg.toml").is_file())
            finally:
                os.chdir(old)

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
            self.assertIn("星尘科技", index)
            toml = (root / "mssg.toml").read_text(encoding="utf-8")
            (root / "mssg.toml").write_text(
                toml.replace('title = "星尘科技"', 'title = "新标题"'),
                encoding="utf-8",
            )
            site.build()
            index = (root / "public" / "index.html").read_text(encoding="utf-8")
            self.assertIn("新标题", index)


if __name__ == "__main__":
    unittest.main()
