"""v0.8.0 测试：模块拆分、Markdown 可配置、插件钩子、图片缓存、
构建性能优化（轻/重分离、模板缓存、搜索增量）、admin token 鉴权。"""

import json
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from mssg import images, markdown
from mssg.hooks import Hooks
from mssg.site import Site, new_site


def make_site(**toml_extra) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="mssg080-"))
    new_site(tmp)
    return tmp


class TestMarkdownConfig(unittest.TestCase):
    def tearDown(self):
        pass

    def _build(self, toml_snippet: str, body: str) -> str:
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        (root / "mssg.toml").write_text(
            '[site]\ntitle="T"\n' + toml_snippet, encoding="utf-8"
        )
        (root / "content" / "a.md").write_text(
            "---\ntitle: A\n---\n\n" + body, encoding="utf-8"
        )
        Site(root).build()
        return (root / "public" / "a.html").read_text(encoding="utf-8")

    def test_default_has_codehilite(self):
        html = self._build("", "```python\nx = 1\n```\n")
        self.assertIn("codehilite", html)

    def test_disable_codehilite(self):
        html = self._build(
            '[markdown]\nextensions = ["extra", "toc", "sane_lists"]\n',
            "```python\nx = 1\n```\n",
        )
        self.assertNotIn("codehilite", html)
        self.assertIn("<code", html)  # 代码块仍在，只是无高亮

    def test_extension_configs(self):
        html = self._build(
            "[markdown.extension_configs.codehilite]\ncss_class = \"mycode\"\n",
            "```python\nx = 1\n```\n",
        )
        self.assertIn('class="mycode"', html)

    def test_parse_api_backward_compat(self):
        # 不传参时行为与旧 API 一致
        html = markdown.parse("# Hi\n")
        self.assertIn("<h1", html)


class TestPlugins(unittest.TestCase):
    def _site_with_plugin(self, plugin_src: str) -> Path:
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        pdir = root / "plugins"
        pdir.mkdir()
        (pdir / "demo.py").write_text(plugin_src, encoding="utf-8")
        (root / "content" / "hello.md").write_text(
            "---\ntitle: Hello\n---\n\nHi.\n", encoding="utf-8"
        )
        return root

    def test_page_html_hook(self):
        root = self._site_with_plugin(
            'def page_html(page, html):\n'
            '    return html.replace("</body>", "<!-- plugin-ok --></body>")\n'
            "\n"
            'HOOKS = {"page_html": page_html}\n'
        )
        Site(root).build()
        html = (root / "public" / "hello.html").read_text(encoding="utf-8")
        self.assertIn("<!-- plugin-ok -->", html)

    def test_build_lifecycle_hooks(self):
        root = self._site_with_plugin(
            "from pathlib import Path\n"
            'LOG = Path(__file__).parent.parent / "plugin.log"\n'
            "def on_start(site):\n"
            '    LOG.write_text("started", encoding="utf-8")\n'
            "def on_read(page):\n"
            '    assert "title" in page\n'
            "def on_finish(site, result):\n"
            '    LOG.write_text("finished pages=%d" % result["pages"], encoding="utf-8")\n'
            "\n"
            'HOOKS = {"build_started": on_start, "page_read": on_read,'
            ' "build_finished": on_finish}\n'
        )
        Site(root).build()
        self.assertEqual(
            (root / "plugin.log").read_text(encoding="utf-8"),
            "finished pages=%d" % Site(root).build()["pages"],
        )

    def test_plugin_load_failure(self):
        root = self._site_with_plugin('raise RuntimeError("boom")\n')
        with self.assertRaises(ValueError) as cm:
            Site(root).build()
        self.assertIn("插件加载失败", str(cm.exception))

    def test_unknown_event(self):
        hooks = Hooks()
        with self.assertRaises(ValueError):
            hooks.register("no_such_event", lambda: None)


class TestImageCache(unittest.TestCase):
    def _site_with_image(self) -> Path:
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        from PIL import Image

        img = Image.new("RGB", (100, 100), "red")
        img.save(root / "static" / "pic.png")
        return root

    def test_image_not_reoptimized(self):
        from mssg import images as _images

        root = self._site_with_image()
        calls = []
        orig = _images.copy_static_file

        def counting(src, dst, max_w, quality):
            if _images.is_image(src):
                calls.append(src.name)
            return orig(src, dst, max_w, quality)

        _images.copy_static_file = counting
        try:
            Site(root).build()
            first = list(calls)
            self.assertIn("pic.png", first)
            calls.clear()
            Site(root).build()  # 无改动：图片应跳过
            self.assertEqual(calls, [])
        finally:
            _images.copy_static_file = orig

    def test_image_config_change_reoptimizes(self):
        from mssg import images as _images

        root = self._site_with_image()
        calls = []
        orig = _images.copy_static_file

        def counting(src, dst, max_w, quality):
            if _images.is_image(src):
                calls.append(src.name)
            return orig(src, dst, max_w, quality)

        _images.copy_static_file = counting
        try:
            Site(root).build()
            calls.clear()
            toml = (root / "mssg.toml").read_text(encoding="utf-8")
            # 脚手架的 [build] 里 image_quality 是注释掉的：取消注释并改值
            new_toml = toml.replace(
                "# image_quality = 82", "image_quality = 50"
            )
            assert new_toml != toml
            (root / "mssg.toml").write_text(new_toml, encoding="utf-8")
            Site(root).build()  # 压缩配置变了：图片应重新处理
            self.assertIn("pic.png", calls)
        finally:
            _images.copy_static_file = orig


class TestIncrementalPerf(unittest.TestCase):
    def test_warm_rebuild_skips_render(self):
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        for i in range(5):
            (root / "content" / ("p%d.md" % i)).write_text(
                "---\ntitle: P%d\n---\n\nBody %d.\n" % (i, i), encoding="utf-8"
            )
        Site(root).build()
        idx = root / "public" / "index.html"
        mtime1 = idx.stat().st_mtime_ns
        r = Site(root).build()
        self.assertFalse(r["rebuilt"])
        # 无改动：列表页连渲染都不做，文件 mtime 不变
        self.assertEqual(idx.stat().st_mtime_ns, mtime1)

    def test_search_index_incremental(self):
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        for i in range(3):
            (root / "content" / ("p%d.md" % i)).write_text(
                "---\ntitle: P%d\n---\n\nOld text %d.\n" % (i, i), encoding="utf-8"
            )
        Site(root).build()
        idx1 = json.loads((root / "public" / "search.json").read_text(encoding="utf-8"))
        (root / "content" / "p1.md").write_text(
            "---\ntitle: P1\n---\n\nNew shiny keyword xyzzy.\n", encoding="utf-8"
        )
        Site(root).build()
        idx2 = json.loads((root / "public" / "search.json").read_text(encoding="utf-8"))
        by_url = {e["url"]: e for e in idx2}
        self.assertEqual(len(idx2), len(idx1))
        self.assertIn("xyzzy", by_url["p1.html"]["text"])
        self.assertIn("Old text 0", by_url["p0.html"]["text"])
        self.assertIn("Old text 2", by_url["p2.html"]["text"])

    def test_feed_gets_light_page_content(self):
        # 单页改动后 feed 重写：未改动页是轻量页，需按需解析正文
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        for i in range(3):
            (root / "content" / ("p%d.md" % i)).write_text(
                "---\ntitle: P%d\ndate: 2026-01-0%d\n---\n\nContent %d.\n" % (i, i + 1, i),
                encoding="utf-8",
            )
        Site(root).build()
        (root / "content" / "p0.md").write_text(
            "---\ntitle: P0\ndate: 2026-01-01\n---\n\nChanged.\n", encoding="utf-8"
        )
        Site(root).build()
        feed = (root / "public" / "feed.xml").read_text(encoding="utf-8")
        self.assertIn("Content 1.", feed)
        self.assertIn("Content 2.", feed)


class TestAdminToken(unittest.TestCase):
    def _serve(self, root: Path, token):
        from mssg import admin

        admin._Handler.app = admin.AdminApp(root)
        admin._Handler.token = token
        srv = ThreadingHTTPServer(("127.0.0.1", 0), admin._Handler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        self.addCleanup(srv.shutdown)
        self.addCleanup(setattr, admin._Handler, "token", None)
        return "http://127.0.0.1:%d" % srv.server_address[1]

    def _get(self, url, cookie=""):
        req = urllib.request.Request(url)
        if cookie:
            req.add_header("Cookie", cookie)
        return urllib.request.urlopen(req, timeout=10)

    def test_token_required(self):
        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        base = self._serve(root, "secret123")
        # 无 token → 403
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self._get(base + "/")
        self.assertEqual(cm.exception.code, 403)
        # 错 token → 403
        with self.assertRaises(urllib.error.HTTPError):
            self._get(base + "/?token=wrong")
        # 对 token → 200，并种下 cookie
        with self._get(base + "/?token=secret123") as r:
            self.assertEqual(r.status, 200)
            set_cookie = r.headers.get("Set-Cookie", "")
        self.assertIn("mssg_token=secret123", set_cookie)
        # cookie 访问 → 200
        with self._get(base + "/", cookie="mssg_token=secret123") as r:
            self.assertEqual(r.status, 200)

    def test_no_auth(self):
        from mssg import admin

        root = make_site()
        self.addCleanup(shutil.rmtree, root, True)
        base = self._serve(root, None)
        with self._get(base + "/") as r:
            self.assertEqual(r.status, 200)


class TestModuleSplit(unittest.TestCase):
    def test_new_api_locations(self):
        # 拆分后 API 保持可用
        from mssg import scaffold, themes, images as _images

        self.assertEqual(set(themes.available_themes()), {"company", "minimal"})
        self.assertTrue(hasattr(scaffold, "new_site"))
        self.assertTrue(hasattr(_images, "copy_static_file"))
        # site.py 重导出
        self.assertEqual(Site.available_themes(), themes.available_themes())
        self.assertIs(new_site, scaffold.new_site)


if __name__ == "__main__":
    unittest.main()
