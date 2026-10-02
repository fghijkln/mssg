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
    def __init__(self, payload, status=200):
        self._data = json.dumps(payload).encode("utf-8")
        self.status = status

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
        """完整新协议：upload-token → 传文件 → manifest 建部署 → 轮询。"""
        seen = {}

        def fake_urlopen(req, timeout=30, context=None):
            url = req.full_url
            ctype = req.headers.get("Content-type", "")
            body = (req.data and "json" in ctype
                    and json.loads(req.data.decode("utf-8")))
            if url.endswith("/upload-token"):
                return _FakeResp(
                    {"success": True, "result": {"jwt": "jwt123"}})
            if url.endswith("/check-missing"):
                seen["hashes"] = body["hashes"]
                return _FakeResp(
                    {"success": True, "result": body["hashes"]})
            if url.endswith("/assets/upload"):
                seen["uploaded"] = [it["key"] for it in body]
                return _FakeResp({"success": True, "result": []})
            if url.endswith("/upsert-hashes"):
                seen["upserted"] = True
                return _FakeResp({"success": True, "result": []})
            if url.endswith("/deployments") and req.method == "POST":
                seen["ctype"] = req.headers.get("Content-type")
                # multipart 里必须有 manifest 字段
                self.assertIn(b'name="manifest"', req.data)
                return _FakeResp(
                    {"success": True,
                     "result": {"id": "dep1", "url": "abc.p.pages.dev"}})
            if "/deployments/dep1" in url:
                return _FakeResp(
                    {"success": True,
                     "result": {
                         "id": "dep1",
                         "url": "abc.p.pages.dev",
                         "latest_stage": {"name": "deploy",
                                          "status": "success"},
                     }})
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
        self.assertEqual(len(seen["hashes"]), 1)
        self.assertEqual(seen["uploaded"], seen["hashes"])
        self.assertTrue(seen["upserted"])
        self.assertIn("multipart/form-data", seen["ctype"])

    def test_file_hash_stable(self):
        h1 = cf._file_hash(b"hello", "index.html")
        h2 = cf._file_hash(b"hello", "index.html")
        h3 = cf._file_hash(b"hello!", "index.html")
        self.assertEqual(h1, h2)
        self.assertNotEqual(h1, h3)
        self.assertEqual(len(h1), 32)

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


class TestDoHFallback(unittest.TestCase):
    def test_is_dns_error(self):
        import socket

        e = cf.urllib.error.URLError(
            socket.gaierror(-2, "Name or service not known")
        )
        self.assertTrue(cf._is_dns_error(e))
        e2 = cf.urllib.error.URLError(ConnectionRefusedError("refused"))
        self.assertFalse(cf._is_dns_error(e2))

    def test_doh_resolve(self):
        cf._doh_cache.clear()
        payload = {
            "Answer": [{"name": "api.cloudflare.com", "type": 1, "data": "1.2.3.4"}]
        }
        with mock.patch.object(
            cf.urllib.request, "urlopen", return_value=_FakeResp(payload)
        ):
            ip = cf._doh_resolve("api.cloudflare.com")
        self.assertEqual(ip, "1.2.3.4")
        # 缓存命中不再请求网络
        with mock.patch.object(
            cf.urllib.request, "urlopen", side_effect=AssertionError("no net")
        ):
            self.assertEqual(cf._doh_resolve("api.cloudflare.com"), "1.2.3.4")
        cf._doh_cache.clear()

    def test_req_falls_back_to_doh(self):
        import socket

        dns_err = cf.urllib.error.URLError(
            socket.gaierror("[Errno 7] No address associated with hostname")
        )
        calls = {"n": 0}

        def fake_urlopen(req, timeout=30, context=None):
            calls["n"] += 1
            raise dns_err

        class FakeOpener:
            def open(self, req, timeout=30):
                return _FakeResp({"success": True, "result": [{"id": "a"}]})

        with mock.patch.object(
            cf.urllib.request, "urlopen", side_effect=fake_urlopen
        ), mock.patch.object(
            cf, "_doh_resolve", return_value="1.2.3.4"
        ), mock.patch.object(
            cf.urllib.request, "build_opener", return_value=FakeOpener()
        ):
            out = cf._req("tok", "GET", "/accounts")
        self.assertTrue(out["success"])
        self.assertEqual(calls["n"], 1)  # 直接请求只试一次

    def test_req_doh_failure_raises_original(self):
        import socket

        dns_err = cf.urllib.error.URLError(socket.gaierror("nope"))
        with mock.patch.object(
            cf.urllib.request, "urlopen", side_effect=dns_err
        ), mock.patch.object(
            cf, "_doh_resolve", side_effect=cf.CloudflareError("doh down")
        ):
            with self.assertRaises(cf.CloudflareError) as cm:
                cf._req("tok", "GET", "/accounts")
        self.assertIn("doh down", str(cm.exception))


class TestSNIConnection(unittest.TestCase):
    @unittest.skipUnless(
        __import__("shutil").which("openssl"), "需要 openssl 生成测试证书"
    )
    def test_tcp_to_ip_sni_to_hostname(self):
        """TCP 连 IP，但 TLS SNI 用真实域名（DoH 备用通道的核心 trick）。"""
        import shutil
        import socket
        import ssl
        import subprocess
        import threading

        with tempfile.TemporaryDirectory() as tmp:
            key = os.path.join(tmp, "k.pem")
            crt = os.path.join(tmp, "c.pem")
            subprocess.run(
                ["openssl", "req", "-x509", "-newkey", "rsa:2048",
                 "-keyout", key, "-out", crt, "-days", "1", "-nodes",
                 "-subj", "/CN=example.com"],
                check=True, capture_output=True,
            )
            seen = {}

            def sni_cb(sock, server_name, ctx):
                seen["sni"] = server_name

            srv_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            srv_ctx.sni_callback = sni_cb
            srv_ctx.load_cert_chain(crt, key)
            lsock = socket.socket()
            lsock.bind(("127.0.0.1", 0))
            lsock.listen(1)
            port = lsock.getsockname()[1]

            def serve():
                conn, _ = lsock.accept()
                try:
                    tls = srv_ctx.wrap_socket(conn, server_side=True)
                    tls.recv(4096)
                    tls.sendall(
                        b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok"
                    )
                    tls.close()
                except Exception:
                    pass

            th = threading.Thread(target=serve, daemon=True)
            th.start()

            cls = cf._sni_conn_class({"example.com": "127.0.0.1"})
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            conn = cls("example.com", port=port, timeout=10, context=ctx)
            conn.request("GET", "/")
            body = conn.getresponse().read()
            th.join(timeout=5)
            lsock.close()

        self.assertEqual(seen.get("sni"), "example.com")
        self.assertEqual(body, b"ok")


class TestTransportHook(unittest.TestCase):
    def tearDown(self):
        cf.set_transport(None)

    def test_transport_last_resort(self):
        calls = {}

        def fake_transport(method, url, headers, body, timeout):
            calls["method"] = method
            calls["auth"] = headers.get("Authorization", "")
            return 200, b'{"success": true, "result": [{"id": "a"}]}'

        cf.set_transport(fake_transport)
        err = cf.urllib.error.URLError(ConnectionRefusedError("refused"))
        with mock.patch.object(
            cf.urllib.request, "urlopen", side_effect=err
        ):
            out = cf._req("tok123", "GET", "/accounts")
        self.assertTrue(out["success"])
        self.assertEqual(calls["method"], "GET")
        self.assertEqual(calls["auth"], "Bearer tok123")

    def test_transport_api_error(self):
        def fake_transport(method, url, headers, body, timeout):
            return 401, b'{"success": false, "errors": [{"message": "bad token"}]}'

        cf.set_transport(fake_transport)
        err = cf.urllib.error.URLError(ConnectionRefusedError("x"))
        with mock.patch.object(
            cf.urllib.request, "urlopen", side_effect=err
        ):
            with self.assertRaises(cf.CloudflareError) as cm:
                cf._req("tok", "GET", "/accounts")
        self.assertIn("bad token", str(cm.exception))

    def test_no_transport_raises_network_error(self):
        err = cf.urllib.error.URLError(ConnectionRefusedError("refused"))
        with mock.patch.object(
            cf.urllib.request, "urlopen", side_effect=err
        ):
            with self.assertRaises(cf.CloudflareError) as cm:
                cf._req("tok", "GET", "/accounts")
        self.assertIn("网络错误", str(cm.exception))


class TestTokenVerify(unittest.TestCase):
    def test_verify_token(self):
        with mock.patch.object(
            cf.urllib.request, "urlopen",
            return_value=_FakeResp({
                "success": True,
                "result": {"id": "t1", "status": "active",
                           "expires_on": "2027-01-01T00:00:00Z"},
            }),
        ):
            info = cf.verify_token("tok")
        self.assertEqual(info["status"], "active")

    def test_list_projects(self):
        with mock.patch.object(
            cf.urllib.request, "urlopen",
            return_value=_FakeResp(
                {"success": True, "result": [{"name": "p1"}]}
            ),
        ):
            projs = cf.list_projects("tok", "acc1")
        self.assertEqual(projs[0]["name"], "p1")

    def test_empty_accounts_ok(self):
        # /accounts 返回空列表不再抛错，由上层决定手动填 Account ID
        with mock.patch.object(
            cf.urllib.request, "urlopen",
            return_value=_FakeResp({"success": True, "result": []}),
        ):
            self.assertEqual(cf.list_accounts("tok"), [])
