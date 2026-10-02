"""生产级特性测试：过滤器、TOC、摘要、分类、RSS、robots、data、新文章。"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from mssg import markdown, template
from mssg.site import Site, new_site


class TestFilters(unittest.TestCase):
    def r(self, tpl, ctx):
        return template.render(tpl, ctx)

    def test_basic(self):
        self.assertEqual(self.r("{{ n|upper }}", {"n": "ab"}), "AB")
        self.assertEqual(self.r("{{ n|lower }}", {"n": "AB"}), "ab")
        self.assertEqual(self.r("{{ n|title }}", {"n": "hello world"}), "Hello World")
        self.assertEqual(self.r("{{ n|trim }}", {"n": "  x  "}), "x")
        self.assertEqual(self.r("{{ n|length }}", {"n": [1, 2, 3]}), "3")
        self.assertEqual(self.r("{{ n|length }}", {"n": "abcd"}), "4")

    def test_chain(self):
        # Jinja2 语义：default 只对未定义变量生效
        self.assertEqual(
            self.r('{{ n|default("n/a")|upper }}', {}), "N/A")
        self.assertEqual(
            self.r('{{ n|default("n/a")|upper }}', {"n": "hi"}), "HI")
        # boolean=true 时对空字符串等 falsy 也生效
        self.assertEqual(
            self.r('{{ n|default("n/a", true)|upper }}', {"n": ""}), "N/A")

    def test_default(self):
        self.assertEqual(self.r("{{ n|default('x') }}", {}), "x")
        self.assertEqual(self.r("{{ n|default('x') }}", {"n": "y"}), "y")

    def test_striptags_escape(self):
        self.assertEqual(self.r("{{ n|striptags }}", {"n": "<b>x</b>"}), "x")
        self.assertEqual(self.r("{{ n|escape }}", {"n": "<b>"}), "&lt;b&gt;")

    def test_urlencode(self):
        # Jinja2 内建 urlencode：空格转 %20，斜杠保留
        self.assertEqual(self.r("{{ n|urlencode }}", {"n": "a b/c"}), "a%20b/c")

    def test_join_first_last(self):
        ctx = {"n": ["a", "b", "c"]}
        self.assertEqual(self.r("{{ n|join }}", ctx), "abc")  # Jinja2 默认无分隔符
        self.assertEqual(self.r('{{ n|join(";") }}', ctx), "a;b;c")
        self.assertEqual(self.r("{{ n|first }}", ctx), "a")
        self.assertEqual(self.r("{{ n|last }}", ctx), "c")

    def test_replace_truncate(self):
        self.assertEqual(
            self.r('{{ n|replace("a", "o") }}', {"n": "banana"}), "bonono")
        # Jinja2 truncate 默认 leeway=5：短串不截断；leeway=0 时精确截断
        self.assertEqual(self.r("{{ n|truncate(3) }}", {"n": "abcdef"}), "abcdef")
        self.assertEqual(
            self.r("{{ n|truncate(5, true, '…', 0) }}", {"n": "abcdefghijklmnop"}),
            "abcd…")
        self.assertEqual(self.r("{{ n|truncate(10) }}", {"n": "abc"}), "abc")

    def test_date(self):
        self.assertEqual(
            self.r('{{ d|date("%Y年%m月%d日") }}', {"d": "2026-10-02"}),
            "2026年10月02日")
        self.assertEqual(
            self.r("{{ d|date }}", {"d": "2026-10-02"}), "2026-10-02")

    def test_unknown_filter(self):
        with self.assertRaises(ValueError):
            self.r("{{ n|nope }}", {"n": "x"})

    def test_comment(self):
        self.assertEqual(self.r("a{# 注释 #}b", {}), "ab")


class TestToc(unittest.TestCase):
    def test_heading_ids(self):
        html = markdown.parse("## 章节标题\n### 子标题\n# 主标题\n")
        self.assertIn('<h2 id="章节标题">', html)
        self.assertIn('<h3 id="子标题">', html)
        self.assertIn('<h1 id="主标题">主标题</h1>', html)  # h1 也有锚点

    def test_extract_toc(self):
        toc = markdown.extract_toc("# 忽略\n## 第二章\n### 2.1 节\n")
        self.assertEqual(len(toc), 2)
        self.assertEqual(toc[0]["level"], 2)
        self.assertEqual(toc[0]["text"], "第二章")
        self.assertEqual(toc[1]["id"], "21-节")

    def test_slugify(self):
        self.assertEqual(markdown.slugify("Hello World"), "hello-world")
        self.assertEqual(markdown.slugify("中文 标题"), "中文-标题")


class TestProductionBuild(unittest.TestCase):
    def _make_site(self, tmp):
        root = new_site(os.path.join(tmp, "demo"))
        (root / "content" / "a.md").write_text(
            "---\ntitle: A\ndate: 2026-10-02\ncategories: [技术]\n"
            "tags: [x]\n---\n\n# A\n\n首段摘要。\n\n<!--more-->\n\n后面很长。\n\n"
            "## 细节\n\n内容。\n",
            encoding="utf-8",
        )
        (root / "data").mkdir(exist_ok=True)
        (root / "data" / "links.json").write_text(
            '{"items": [{"name": "友链", "url": "https://e.com"}]}',
            encoding="utf-8",
        )
        (root / "templates" / "index.html").write_text(
            "{% for p in pages %}{{ p.title }}|{{ p.summary_text }};"
            "{% endfor %}{{ data.links['items']|first|upper }}",
            encoding="utf-8",
        )
        return root

    def test_summary_toc_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_site(tmp)
            site = Site(root)
            site.build()
            # 摘要：more 之前
            idx = (root / "public" / "index.html").read_text(encoding="utf-8")
            self.assertIn("首段摘要。", idx)
            self.assertNotIn("后面很长", idx)
            # TOC
            page = (root / "public" / "a.html").read_text(encoding="utf-8")
            self.assertIn('id="细节"', page)
            # 分类页
            cat = (root / "public" / "categories" / "技术.html").read_text(
                encoding="utf-8")
            self.assertIn("A", cat)
            # data + filter 进模板
            self.assertIn("友链".upper(), idx)

    def test_summary_fallback_first_paragraph(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            (root / "content" / "b.md").write_text(
                "---\ntitle: B\ndate: 2026-10-01\n---\n\n# B\n\n第一段。\n\n第二段。\n",
                encoding="utf-8",
            )
            (root / "templates" / "index.html").write_text(
                "{% for p in pages %}{{ p.title }}:{{ p.summary_text }};{% endfor %}",
                encoding="utf-8",
            )
            site = Site(root)
            site.build()
            idx = (root / "public" / "index.html").read_text(encoding="utf-8")
            self.assertIn("B:第一段。;", idx)
            self.assertNotIn("第二段", idx)

    def test_rss_robots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_site(tmp)
            Site(root).build()
            rss = (root / "public" / "feed_rss.xml").read_text(encoding="utf-8")
            self.assertIn("<rss version=", rss)
            self.assertIn("<item>", rss)
            robots = (root / "public" / "robots.txt").read_text(encoding="utf-8")
            self.assertIn("User-agent: *", robots)

    def test_rss_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_site(tmp)
            (root / "mssg.toml").write_text(
                '[site]\ntitle = "t"\n[build]\nrss = false\nrobots = false\n'
                "category_pages = false\n",
                encoding="utf-8",
            )
            Site(root).build()
            self.assertFalse((root / "public" / "feed_rss.xml").exists())
            self.assertFalse((root / "public" / "robots.txt").exists())
            self.assertFalse((root / "public" / "categories").exists())

    def test_new_post(self):
        import sys as _sys
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            cwd = os.getcwd()
            os.chdir(root)
            try:
                _sys.argv = ["mssg", "post", "my-post", "-t", "我的文章"]
                from mssg.cli import main
                self.assertEqual(main(), 0)
                p = root / "content" / "my-post.md"
                self.assertTrue(p.exists())
                self.assertIn("我的文章", p.read_text(encoding="utf-8"))
                # 重复创建应报错
                _sys.argv = ["mssg", "post", "my-post"]
                self.assertEqual(main(), 1)
            finally:
                os.chdir(cwd)

    def test_parallel_build_many_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            for i in range(30):
                (root / "content" / f"p{i}.md").write_text(
                    "---\ntitle: P%d\ndate: 2026-09-%02d\n---\n\n# P%d\n\n正文。\n"
                    % (i, (i % 28) + 1, i),
                    encoding="utf-8",
                )
            result = Site(root).build()
            # 30 篇 + hello（draft.md 是草稿，默认排除）
            self.assertEqual(result["pages"], 31)
            self.assertTrue((root / "public" / "p29.html").exists())


if __name__ == "__main__":
    unittest.main()
