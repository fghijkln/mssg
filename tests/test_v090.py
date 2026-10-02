"""v0.9.0 测试：依赖瘦身（yaml_subset/可选依赖）、shortcodes、
page bundles、asset pipeline（压缩+fingerprint）、嵌套菜单。"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from mssg import assets, shortcodes, yaml_subset
from mssg.site import Site, new_site


def make_site() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="mssg090-"))
    new_site(tmp)
    return tmp


def build_page(root: Path, name: str, body: str, toml_extra: str = "") -> str:
    (root / "content" / name).write_text(
        "---\ntitle: T\n---\n\n" + body, encoding="utf-8"
    )
    if toml_extra:
        p = root / "mssg.toml"
        p.write_text(
            p.read_text(encoding="utf-8") + "\n" + toml_extra, encoding="utf-8"
        )
    Site(root).build()
    out = root / "public" / name.replace(".md", ".html")
    return out.read_text(encoding="utf-8")


class TestYamlSubset(unittest.TestCase):
    def test_scalars(self):
        m = yaml_subset.loads(
            "title: 你好\nn: 42\nf: 1.5\nt: true\nff: no\nnil: null\nempty:\n"
        )
        self.assertEqual(m["title"], "你好")
        self.assertEqual(m["n"], 42)
        self.assertEqual(m["f"], 1.5)
        self.assertIs(m["t"], True)
        self.assertIs(m["ff"], False)
        self.assertIsNone(m["nil"])
        self.assertIsNone(m["empty"])

    def test_quoted_and_comment(self):
        m = yaml_subset.loads('a: "x # y"\nb: a#b\nc: val # 注释\nd: # 纯注释\n')
        self.assertEqual(m["a"], "x # y")
        self.assertEqual(m["b"], "a#b")
        self.assertEqual(m["c"], "val")
        self.assertIsNone(m["d"])

    def test_lists(self):
        m = yaml_subset.loads("tags: [a, b]\nlist:\n  - x # 注释\n  - 'y # z'\n")
        self.assertEqual(m["tags"], ["a", "b"])
        self.assertEqual(m["list"], ["x", "y # z"])

    def test_nested_and_literal(self):
        m = yaml_subset.loads(
            "author:\n  name: 小王\n  email: x@y.z\ndesc: |\n  第一行\n  第二行\n"
        )
        self.assertEqual(m["author"], {"name": "小王", "email": "x@y.z"})
        self.assertEqual(m["desc"], "第一行\n第二行\n")

    def test_date_like(self):
        from datetime import date

        m = yaml_subset.loads("date: 2026-10-02\n")
        self.assertEqual(m["date"], date(2026, 10, 2))

    def test_unicode_key(self):
        m = yaml_subset.loads("标题: 你好\n")
        self.assertEqual(m["标题"], "你好")

    def test_dumps_roundtrip(self):
        data = {"title": "T", "tags": ["a", "b"], "draft": True, "n": 3}
        m = yaml_subset.loads(yaml_subset.dumps(data))
        self.assertEqual(m["title"], "T")
        self.assertEqual(m["tags"], ["a", "b"])
        self.assertIs(m["draft"], True)
        self.assertEqual(m["n"], 3)

    def test_frontmatter_uses_subset(self):
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        html = build_page(root, "a.md", "hi")
        self.assertIn("T", html)


class TestShortcodes(unittest.TestCase):
    def test_parse_args(self):
        args, kwargs = shortcodes.parse_args('a b key="v v" k2=v2')
        self.assertEqual(args, ["a", "b"])
        self.assertEqual(kwargs, {"key": "v v", "k2": "v2"})

    def test_figure(self):
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        (root / "content" / "p.png").write_bytes(b"not a real png")
        html = build_page(
            root, "a.md", '{{< figure src="p.png" title="图注" alt="A" >}}'
        )
        self.assertIn("<figure>", html)
        self.assertIn('src="p.png"', html)
        self.assertIn("<figcaption>图注</figcaption>", html)

    def test_youtube(self):
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        html = build_page(root, "a.md", "{{< youtube dQw4w9WgXcQ >}}")
        self.assertIn("youtube-nocookie.com/embed/dQw4w9WgXcQ", html)

    def test_youtube_bad_id_kept(self):
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        html = build_page(root, "a.md", "{{< youtube !! >}}")
        self.assertIn("youtube", html)  # 非法 ID：保留原文

    def test_custom_shortcode(self):
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        d = root / "templates" / "shortcodes"
        d.mkdir(parents=True)
        (d / "note.html").write_text(
            '<div class="note">{{ kwargs.text }}</div>', encoding="utf-8"
        )
        html = build_page(root, "a.md", '{{< note text="你好" >}}')
        self.assertIn('<div class="note">你好</div>', html)

    def test_unknown_kept(self):
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        html = build_page(root, "a.md", '{{< nosuch x="1" >}}')
        self.assertIn("nosuch", html)  # 未知：保留原文

    def test_missing_image_warns_and_keeps(self):
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        with self.assertWarns(UserWarning):
            html = build_page(root, "a.md", '{{< image src="nope.jpg" >}}')
        self.assertIn("nope.jpg", html)


class TestPageBundles(unittest.TestCase):
    def _bundle(self, root: Path):
        from PIL import Image

        d = root / "content" / "post" / "bundle"
        d.mkdir(parents=True)
        Image.new("RGB", (800, 600), "red").save(d / "photo.jpg")
        (d / "slides.pdf").write_bytes(b"%PDF-1.4 fake")
        (d / "index.md").write_text(
            "---\ntitle: B\n---\n\n{{< image src=\"photo.jpg\" width=\"400\" >}}",
            encoding="utf-8",
        )

    def test_bundle_resources_synced(self):
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        self._bundle(root)
        Site(root).build()
        out = root / "public" / "post" / "bundle"
        self.assertTrue((out / "index.html").is_file())
        self.assertTrue((out / "photo.jpg").is_file())  # 原图同步
        self.assertTrue((out / "slides.pdf").is_file())  # 非图片也同步
        resized = out / "photo-400w.jpg"
        self.assertTrue(resized.is_file())
        from PIL import Image

        self.assertEqual(Image.open(resized).size, (400, 300))
        html = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn('src="photo-400w.jpg"', html)

    def test_bundle_image_change_rebuilds(self):
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        self._bundle(root)
        Site(root).build()
        out = root / "public" / "post" / "bundle" / "photo-400w.jpg"
        from PIL import Image

        self.assertEqual(Image.open(out).getpixel((10, 10))[0], 254)
        import time

        time.sleep(0.05)
        Image.new("RGB", (800, 600), "blue").save(
            root / "content" / "post" / "bundle" / "photo.jpg"
        )
        Site(root).build()
        px = Image.open(out).getpixel((10, 10))
        self.assertEqual(px[2], 254)  # 缩放图已更新为蓝色

    def test_stale_bundle_cleaned(self):
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        self._bundle(root)
        Site(root).build()
        (root / "content" / "post" / "bundle" / "photo.jpg").unlink()
        Site(root).build()
        out = root / "public" / "post" / "bundle"
        self.assertFalse((out / "photo.jpg").exists())
        self.assertFalse((out / "photo-400w.jpg").exists())
        cache = json.loads(
            (root / "public" / ".mssg" / "cache.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(cache.get("genfiles"), ["post/bundle/slides.pdf"])


class TestAssets(unittest.TestCase):
    def test_minify_css(self):
        out = assets.minify_css("/* 注释 */\na {\n  color: red; \n}\n")
        self.assertNotIn("注释", out)
        self.assertLess(len(out), 25)
        # 字符串里的空格保留
        out2 = assets.minify_css('a::after{content:"a b"}')
        self.assertIn('"a b"', out2)

    def test_minify_js(self):
        out = assets.minify_js("// 注释\nvar x = 1;  \n\n/* 块 */\nvar s = 'a//b';\n")
        self.assertNotIn("注释", out)
        self.assertIn("'a//b'", out)  # 字符串里的 // 保留
        self.assertNotIn("\n\n", out)

    def test_fingerprinted_name(self):
        n = assets.fingerprinted_name("css/a.css", b"hello")
        self.assertRegex(n, r"^css/a\.[0-9a-f]{8}\.css$")
        n2 = assets.fingerprinted_name("a.min.js", b"hello")
        self.assertRegex(n2, r"^a\.min\.[0-9a-f]{8}\.js$")

    def test_build_minify_fingerprint(self):
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        (root / "static").mkdir(exist_ok=True)
        (root / "static" / "app.css").write_text(
            "/* c */\n.a {\n  color: red;\n}\n", encoding="utf-8"
        )
        p = root / "mssg.toml"
        p.write_text(
            p.read_text(encoding="utf-8")
            + "\n[assets]\nminify = true\nfingerprint = true\n",
            encoding="utf-8",
        )
        Site(root).build()
        css_files = list((root / "public").glob("app.*.css"))
        self.assertEqual(len(css_files), 1)
        content = css_files[0].read_text(encoding="utf-8")
        self.assertNotIn("/* c */", content)
        self.assertIn(".a{color:red}", content)

    def test_asset_template_global(self):
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        (root / "static").mkdir(exist_ok=True)
        (root / "static" / "app.css").write_text(".a{color:red}", encoding="utf-8")
        (root / "templates").mkdir(exist_ok=True)
        (root / "templates" / "page.html").write_text(
            '<link href="{{ asset("app.css") }}">', encoding="utf-8"
        )
        (root / "content" / "a.md").write_text(
            "---\ntitle: A\n---\n\nhi\n", encoding="utf-8"
        )
        p = root / "mssg.toml"
        p.write_text(
            p.read_text(encoding="utf-8") + "\n[assets]\nfingerprint = true\n",
            encoding="utf-8",
        )
        Site(root).build()
        html = (root / "public" / "a.html").read_text(encoding="utf-8")
        import re

        m = re.search(r'app\.[0-9a-f]{8}\.css', html)
        self.assertIsNotNone(m)

    def test_css_change_bumps_fingerprint(self):
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        (root / "static").mkdir(exist_ok=True)
        css = root / "static" / "app.css"
        css.write_text(".a{color:red}", encoding="utf-8")
        p = root / "mssg.toml"
        p.write_text(
            p.read_text(encoding="utf-8") + "\n[assets]\nfingerprint = true\n",
            encoding="utf-8",
        )
        Site(root).build()
        first = [f.name for f in (root / "public").glob("app.*.css")]
        css.write_text(".a{color:blue}", encoding="utf-8")
        Site(root).build()
        second = [f.name for f in (root / "public").glob("app.*.css")]
        self.assertEqual(len(second), 1)
        self.assertNotEqual(first, second)  # 旧指纹文件已清理


class TestNestedMenu(unittest.TestCase):
    def test_children_render(self):
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        p = root / "mssg.toml"
        t = p.read_text(encoding="utf-8")
        t = t.replace(
            '[[site.menu]]\nname = "产品"\nurl = "/products.html"\nweight = 2',
            '[[site.menu]]\nname = "产品"\nurl = "/products.html"\nweight = 2\n'
            '[[site.menu.children]]\nname = "手机"\nurl = "/p.html"\nweight = 1',
        )
        p.write_text(t, encoding="utf-8")
        Site(root).build()
        html = (root / "public" / "index.html").read_text(encoding="utf-8")
        self.assertIn("nav-drop", html)
        self.assertIn("/p.html", html)

    def test_menu_sort_tolerates_missing_weight(self):
        from mssg.template import _f_menu_sort

        items = [{"name": "b"}, {"name": "a", "weight": 1}]
        self.assertEqual(
            [m["name"] for m in _f_menu_sort(items)], ["b", "a"]
        )


if __name__ == "__main__":
    unittest.main()
