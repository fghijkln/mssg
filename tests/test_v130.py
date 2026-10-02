"""mssg v0.13.0 测试：Cloudflare Pages 直接部署（全部 mock 网络）。"""

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mssg import cloudflare as cf


class _FakeResp:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ok(result):
    return _FakeResp({"success": True, "result": result})


def _fail(msg, code=1000):
    return _FakeResp(
        {"success": False, "errors": [{"code": code, "message": msg}]}
    )


class TestCloudflare(unittest.TestCase):
    def test_sanitize_project_name(self):
        self.assertEqual(cf.sanitize_project_name("My Site!"), "my-site")
        self.assertEqual(cf.sanitize_project_name("星尘科技"), "mssg-site")
        self.assertEqual(cf.sanitize_project_name(""), "mssg-site")
        self.assertTrue(len(cf.sanitize_project_name("a" * 100)) <= 58)

    def test_collect_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            pub = Path(tmp) / "public"
            (pub / "assets").mkdir(parents=True)
            (pub / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
            (pub / "assets" / "style.css").write_text("a{}", encoding="utf-8")
            files = cf.collect_files(pub)
            names = [f[0] for f in files]
            self.assertEqual(names, ["/assets/style.css", "/index.html"])
            self.assertEqual(files[1][2], "text/html")

    def test_collect_files_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(cf.CloudflareError):
                cf.collect_files(tmp)

    def test_list_accounts(self):
        with mock.patch.object(
            cf.urllib.request, "urlopen",
            return_value=_ok([{"id": "acc1", "name": "A"}]),
        ):
            accs = cf.list_accounts("tok")
        self.assertEqual(accs, [{"id": "acc1", "name": "A"}])

    def test_api_error_raises(self):
        with mock.patch.object(
            cf.urllib.request, "urlopen", return_value=_fail("bad token")
        ):
            with self.assertRaises(cf.CloudflareError) as cm:
                cf.list_accounts("bad")
        self.assertIn("bad token", str(cm.exception))

    def test_get_or_create_project_exists(self):
        with mock.patch.object(
            cf.urllib.request, "urlopen",
            return_value=_ok({"name": "p", "subdomain": "p.pages.dev"}),
        ):
            proj, created = cf.get_or_create_project("t", "acc", "p")
        self.assertFalse(created)
        self.assertEqual(proj["name"], "p")

    def test_get_or_create_project_creates(self):
        calls = []

        def fake_urlopen(req, timeout=30):
            calls.append(req.full_url)
            if req.method == "GET":
                return _fail("not found", code=8000002)
            return _ok({"name": "np"})

        with mock.patch.object(cf.urllib.request, "urlopen", side_effect=fake_urlopen):
            proj, created = cf.get_or_create_project("t", "acc", "np")
        self.assertTrue(created)
        self.assertTrue(any("projects/acc" in u or "/projects" in u for u in calls))

    def test_deploy_directory_flow(self):
        seen = {}

        def fake_urlopen(req, timeout=30):
            url = req.full_url
            if url.endswith("/deployments") and req.method == "POST":
                seen["body"] = req.data
                seen["ctype"] = req.headers.get("Content-type")
                return _ok({"id": "dep1", "url": "abc.p.pages.dev"})
            if "/deployments/dep1" in url:
                return _ok(
                    {
                        "id": "dep1",
                        "url": "abc.p.pages.dev",
                        "latest_stage": {"name": "deploy", "status": "success"},
                    }
                )
            raise AssertionError("unexpected " + url)

        with tempfile.TemporaryDirectory() as tmp:
            pub = Path(tmp)
            (pub / "index.html").write_text("x", encoding="utf-8")
            with mock.patch.object(
                cf.urllib.request, "urlopen", side_effect=fake_urlopen
            ), mock.patch.object(cf.time, "sleep"):
                out = cf.deploy_directory("t", "acc", "p", pub)
        self.assertEqual(out["project_url"], "https://p.pages.dev")
        self.assertEqual(out["url"], "https://abc.p.pages.dev")
        self.assertEqual(out["deployment_id"], "dep1")
        # multipart 字段名带前导斜杠
        self.assertIn(b'name="/index.html"', seen["body"])
        self.assertIn("multipart/form-data", seen["ctype"])

    def test_wait_failure_raises(self):
        with mock.patch.object(
            cf.urllib.request,
            "urlopen",
            return_value=_ok(
                {"id": "d", "latest_stage": {"name": "deploy", "status": "failure"}}
            ),
        ), mock.patch.object(cf.time, "sleep"):
            with self.assertRaises(cf.CloudflareError):
                cf.wait_for_deployment("t", "a", "p", "d", timeout=5)


if __name__ == "__main__":
    unittest.main()
