"""mssg v0.6.0 功能测试：i18n / 站内搜索 / admin / 图片优化 / 联系表单。"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mssg.site import Site, new_site


def _make_i18n_site(tmp):
    """双语站点：中文默认 + 英文（脚手架已自带 i18n，这里微调英文标题以区分测试）。"""
    root = new_site(os.path.join(tmp, "bi"))
    (root / "content" / "about.en.md").write_text(
        "---\ntitle: About Us\ndate: 2026-10-02\n---\n\n# About Us\n\nEnglish content.\n",
        encoding="utf-8",
    )
    (root / "content" / "hello.en.md").write_text(
        "---\ntitle: Hello World\ndate: 2026-10-02\ntags: [news]\n---\n\n# Hello World\n",
        encoding="utf-8",
    )
    toml = (root / "mssg.toml").read_text(encoding="utf-8")
    toml = toml.replace(
        '[site.en]\ntitle = "Stardust"',
        '[site.en]\ntitle = "Stardust EN"',
    )
    toml = toml.replace(
        'description = "Stardust builds collaboration tools for small teams, turning ideas into products."',
        'description = "English description."',
    )
    (root / "mssg.toml").write_text(toml, encoding="utf-8")
    return root


class TestI18n(unittest.TestCase):
    def test_split_lang(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "s"))
            # 默认脚手架是双语；显式只配 zh 时恢复单语行为
            toml = (root / "mssg.toml").read_text(encoding="utf-8")
            toml = toml.replace('langs = ["zh", "en"]', 'langs = ["zh"]')
            (root / "mssg.toml").write_text(toml, encoding="utf-8")
            site = Site(root)
            self.assertEqual(site._langs(), ["zh"])
            self.assertEqual(site._split_lang("about.md"), ("zh", "about.md"))

    def test_split_lang_multi(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_i18n_site(tmp)
            site = Site(root)
            self.assertEqual(site._langs(), ["zh", "en"])
            self.assertEqual(site._split_lang("about.en.md"), ("en", "about.md"))
            self.assertEqual(site._split_lang("a/b.en.md"), ("en", "a/b.md"))
            self.assertEqual(site._split_lang("about.md"), ("zh", "about.md"))
            # 非配置语言的后缀不认作语言
            self.assertEqual(site._split_lang("about.fr.md"), ("zh", "about.fr.md"))

    def test_build_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_i18n_site(tmp)
            Site(root).build()
            pub = root / "public"
            self.assertTrue((pub / "about.html").exists())
            self.assertTrue((pub / "en" / "about.html").exists())
            self.assertTrue((pub / "en" / "index.html").exists())
            self.assertTrue((pub / "en" / "archive.html").exists())
            self.assertTrue((pub / "en" / "feed.xml").exists())
            self.assertTrue((pub / "en" / "search.html").exists())
            # 英文标签页独立
            self.assertTrue((pub / "en" / "tags" / "news.html").exists())

    def test_per_lang_site_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_i18n_site(tmp)
            Site(root).build()
            pub = root / "public"
            en_about = (pub / "en" / "about.html").read_text(encoding="utf-8")
            zh_about = (pub / "about.html").read_text(encoding="utf-8")
            self.assertIn("Stardust EN", en_about)
            self.assertIn("星尘科技", zh_about)
            self.assertIn('lang="en"', en_about)
            self.assertIn('lang="zh"', zh_about)

    def test_hreflang(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_i18n_site(tmp)
            Site(root).build()
            zh_about = (root / "public" / "about.html").read_text(encoding="utf-8")
            self.assertIn('hreflang="zh"', zh_about)
            self.assertIn('hreflang="en"', zh_about)
            self.assertIn("/en/about.html", zh_about)

    def test_bilingual_scaffold_default(self):
        """脚手架默认双语：en/ 页面、中文/EN 切换器、hreflang 齐全。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "bi"), theme="novacore")
            result = Site(root).build()
            self.assertEqual(result["pages"], 8)
            pub = root / "public"
            for f in ("en/index.html", "en/about.html", "en/products.html",
                      "en/hello.html", "en/contact.html"):
                self.assertTrue((pub / f).exists(), f)
            en_idx = (pub / "en" / "index.html").read_text(encoding="utf-8")
            self.assertIn("Small team, big-company speed", en_idx)
            self.assertIn("中文", en_idx)
            self.assertIn('<a href="/en/products.html">Products</a>', en_idx)
            self.assertIn('lang="en"', en_idx)
            zh_idx = (pub / "index.html").read_text(encoding="utf-8")
            self.assertIn('hreflang="en"', zh_idx)
            self.assertIn('<a href="/en/index.html">EN</a>', zh_idx)

    def test_monolingual_unchanged(self):
        """只配一种语言时行为与旧版一致：无 en/ 目录。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "s"))
            toml = (root / "mssg.toml").read_text(encoding="utf-8")
            toml = toml.replace('langs = ["zh", "en"]', 'langs = ["zh"]')
            (root / "mssg.toml").write_text(toml, encoding="utf-8")
            Site(root).build()
            self.assertFalse((root / "public" / "en").exists())


class TestSearch(unittest.TestCase):
    def test_search_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "s"))
            Site(root).build()
            pub = root / "public"
            self.assertTrue((pub / "search.json").exists())
            self.assertTrue((pub / "search.html").exists())
            items = json.loads((pub / "search.json").read_text(encoding="utf-8"))
            urls = {i["url"] for i in items}
            self.assertIn("hello.html", urls)
            self.assertTrue(all("title" in i and "text" in i for i in items))
            # 正文是纯文本（HTML 已剥离）
            hello = next(i for i in items if i["url"] == "hello.html")
            self.assertNotIn("<", hello["text"])

    def test_search_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "s"))
            toml = (root / "mssg.toml").read_text(encoding="utf-8")
            toml = toml.replace("[build]", "[build]\nsearch = false", 1)
            (root / "mssg.toml").write_text(toml, encoding="utf-8")
            Site(root).build()
            self.assertFalse((root / "public" / "search.json").exists())
            self.assertFalse((root / "public" / "search.html").exists())


class TestImageOptimize(unittest.TestCase):
    def test_resize_and_compress(self):
        pytest = None
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow 未安装")
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "s"))
            img = Image.new("RGB", (2000, 1000), (200, 30, 30))
            img.save(root / "static" / "big.jpg", quality=95)
            Site(root).build()
            out = root / "public" / "big.jpg"
            self.assertTrue(out.exists())
            got = Image.open(out)
            self.assertEqual(got.width, 1600)  # 默认 image_max_width
            self.assertLess(out.stat().st_size, (root / "static" / "big.jpg").stat().st_size)

    def test_small_image_kept(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow 未安装")
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "s"))
            img = Image.new("RGB", (100, 100), (30, 200, 30))
            img.save(root / "static" / "small.png")
            Site(root).build()
            out = root / "public" / "small.png"
            self.assertTrue(out.exists())
            self.assertEqual(Image.open(out).size, (100, 100))

    def test_corrupt_image_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "s"))
            (root / "static" / "bad.jpg").write_bytes(b"not an image")
            Site(root).build()  # 不应炸，回退为普通拷贝
            self.assertTrue((root / "public" / "bad.jpg").exists())


class TestContactForm(unittest.TestCase):
    def test_form_hint_without_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "s"))
            Site(root).build()
            html = (root / "public" / "contact.html").read_text(encoding="utf-8")
            self.assertIn("尚未配置", html)
            self.assertNotIn("<form", html)

    def test_form_action_with_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "s"))
            toml = (root / "mssg.toml").read_text(encoding="utf-8")
            toml = toml.replace(
                'endpoint = ""', 'endpoint = "https://formspree.io/f/abc"'
            )
            (root / "mssg.toml").write_text(toml, encoding="utf-8")
            Site(root).build()
            html = (root / "public" / "contact.html").read_text(encoding="utf-8")
            self.assertIn('action="https://formspree.io/f/abc"', html)
            self.assertIn('name="email"', html)


class TestAdmin(unittest.TestCase):
    def test_safe_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "s"))
            from mssg.admin import AdminApp

            app = AdminApp(root)
            with self.assertRaises(ValueError):
                app._safe_path("../mssg.toml")
            with self.assertRaises(ValueError):
                app._safe_path("x.txt")

    def test_save_and_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "s"))
            from mssg.admin import AdminApp

            app = AdminApp(root)
            rel = app.save_page(
                {
                    "rel": ["post/new.md"],
                    "title": ["测试文章"],
                    "date": ["2026-10-03"],
                    "tags": ["a, b"],
                    "categories": [""],
                    "body": ["# 正文\n"],
                }
            )
            self.assertEqual(rel, "post/new.md")
            p = root / "content" / "post" / "new.md"
            self.assertTrue(p.exists())
            text = p.read_text(encoding="utf-8")
            self.assertIn("title: 测试文章", text)
            # 重新 build 能认出新文章
            Site(root).build()
            self.assertTrue((root / "public" / "post" / "new.html").exists())
            # 列表页包含
            index = app.render_index()
            self.assertIn("测试文章", index)

    def test_edit_preserves_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "s"))
            from mssg.admin import AdminApp
            from mssg.frontmatter import split as _split

            app = AdminApp(root)
            # hello.md 原有 tags，编辑时只改标题
            app.save_page(
                {
                    "rel": ["hello.md"],
                    "title": ["新标题"],
                    "date": ["2026-10-02"],
                    "tags": [""],
                    "categories": [""],
                    "body": ["正文\n"],
                }
            )
            meta, _ = _split((root / "content" / "hello.md").read_text(encoding="utf-8"))
            self.assertEqual(meta["title"], "新标题")
            self.assertNotIn("tags", meta)  # 清空标签时移除


class TestTheme(unittest.TestCase):
    def test_available_themes(self):
        self.assertIn("company", Site.available_themes())
        self.assertIn("minimal", Site.available_themes())

    def test_new_site_has_no_templates_dir(self):
        # 模板来自内置主题，脚手架不再复制模板文件
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            self.assertFalse((root / "templates").exists())
            Site(root).build()
            index = (root / "public" / "index.html").read_text(encoding="utf-8")
            self.assertIn("星尘科技", index)
            self.assertTrue((root / "public" / "style.css").exists())

    def test_switch_theme(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            Site(root).build()
            company_index = (root / "public" / "index.html").read_text(encoding="utf-8")
            self.assertIn("cta-row", company_index)
            toml = (root / "mssg.toml").read_text(encoding="utf-8")
            toml = toml.replace('theme = "company"', 'theme = "minimal"')
            (root / "mssg.toml").write_text(toml, encoding="utf-8")
            Site(root).build()
            minimal_index = (root / "public" / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("cta-row", minimal_index)
            self.assertIn("星尘科技", minimal_index)  # 内容配置不变
            css = (root / "public" / "style.css").read_text(encoding="utf-8")
            self.assertIn("--blue", css)

    def test_unknown_theme(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            toml = (root / "mssg.toml").read_text(encoding="utf-8")
            toml = toml.replace('theme = "company"', 'theme = "nope"')
            (root / "mssg.toml").write_text(toml, encoding="utf-8")
            with self.assertRaises(ValueError) as cm:
                Site(root).build()
            self.assertIn("未知主题", str(cm.exception))

    def test_new_site_unknown_theme(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                new_site(os.path.join(tmp, "demo"), theme="nope")

    def test_canonical_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            toml = (root / "mssg.toml").read_text(encoding="utf-8")
            toml = toml.replace('base_url = ""', 'base_url = "https://example.com"')
            (root / "mssg.toml").write_text(toml, encoding="utf-8")
            Site(root).build()
            about = (root / "public" / "about.html").read_text(encoding="utf-8")
            self.assertIn(
                '<link rel="canonical" href="https://example.com/about.html">', about
            )
            index = (root / "public" / "index.html").read_text(encoding="utf-8")
            self.assertIn(
                '<link rel="canonical" href="https://example.com/">', index
            )

    def test_no_canonical_without_base_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = new_site(os.path.join(tmp, "demo"))
            Site(root).build()
            about = (root / "public" / "about.html").read_text(encoding="utf-8")
            self.assertNotIn("rel=\"canonical\"", about)


if __name__ == "__main__":
    unittest.main()
