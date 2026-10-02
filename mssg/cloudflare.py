"""Cloudflare Pages 直接部署（Direct Upload API）。

只用 Python 标准库（urllib），无第三方依赖。流程：

1. ``list_accounts(token)`` → 账号列表（取第一个即可）
2. ``get_or_create_project(token, account_id, name)`` → 项目不存在则创建
3. ``deploy_directory(token, account_id, project, public_dir)``
   → multipart 上传 public/ 下所有文件 → 轮询部署状态 → 返回线上地址

Token 权限：Cloudflare Pages → Edit（在
https://dash.cloudflare.com/profile/api-tokens 创建自定义 Token）。
"""

import base64
import hashlib
import json
import mimetypes
import os
import secrets
import socket
import ssl
import time
import http.client
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://api.cloudflare.com/client/v4"
API_HOST = "api.cloudflare.com"
MAX_FILE_SIZE = 25 * 1024 * 1024  # Cloudflare 单文件上限 25 MiB
MAX_FILES = 20000  # Cloudflare 单次部署文件数上限
POLL_INTERVAL = 3
POLL_TIMEOUT = 180

# 备用 DNS（DoH）：先走普通域名（仍需系统 DNS，但可能只坏了个别域名），
# 再走直连 IP（完全不依赖系统 DNS）
_DOH_URLS_HOST = [
    "https://cloudflare-dns.com/dns-query?name={host}&type=A",
    "https://dns.google/resolve?name={host}&type=A",
]
_DOH_URLS_IP = [
    "https://1.1.1.1/dns-query?name={host}&type=A",
    "https://8.8.8.8/resolve?name={host}&type=A",
]
_doh_cache = {}

# 可插拔传输层：fn(method, url, headers:dict, body:bytes|None, timeout)
# -> (status:int, body:bytes)。None 表示用默认 urllib 通道。
# App 可将其设为经 WebView（Chromium 网络栈）发请求的实现，
# 用于系统 DNS/socket 全坏的手机。
_transport = None


def set_transport(fn):
    """设置备用传输实现（如 App 内 WebView 通道）。"""
    global _transport
    _transport = fn


class CloudflareError(Exception):
    """Cloudflare API 返回 success=false 或网络层失败。"""


def _is_dns_error(e):
    """URLError 是否由 DNS 解析失败引起。"""
    r = getattr(e, "reason", None)
    if isinstance(r, socket.gaierror):
        return True  # getaddrinfo 错误恒为 DNS 问题
    msg = str(r).lower()
    return isinstance(r, OSError) and any(
        k in msg
        for k in (
            "address associated with hostname",
            "name or service not known",
            "nodename nor servname",
            "temporary failure in name resolution",
        )
    )


def _doh_resolve(host):
    """经 DoH 解析 host → IP。先试普通域名，再试直连 IP。按进程缓存。"""
    if host in _doh_cache:
        return _doh_cache[host]
    errs = []
    for url in _DOH_URLS_HOST + _DOH_URLS_IP:
        try:
            ctx = ssl.create_default_context()
            if url.startswith("https://1.1.1.1") or url.startswith("https://8.8.8.8"):
                ctx.check_hostname = False  # IP 直连引导阶段只验链；
                # 后续 API 连接仍会对 api.cloudflare.com 做完整证书校验
            req = urllib.request.Request(
                url.format(host=host), headers={"Accept": "application/dns-json"}
            )
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for ans in data.get("Answer", []):
                if ans.get("type") == 1 and ans.get("data"):
                    _doh_cache[host] = ans["data"]
                    return ans["data"]
            errs.append("%s: 无有效 A 记录" % url)
        except Exception as e:
            errs.append("%s: %s" % (url, e))
    raise CloudflareError("DNS 解析失败（备用 DNS 也不可用）：%s" % "; ".join(errs))


def _sni_conn_class(ip_map):
    """HTTPSConnection 工厂：TCP 连 IP，TLS 用真实域名做 SNI/证书校验。"""

    class _Conn(http.client.HTTPSConnection):
        def __init__(self, host, **kw):
            self._real_host = host
            super().__init__(ip_map.get(host, host), **kw)

        def connect(self):
            http.client.HTTPConnection.connect(self)
            self.sock = self._context.wrap_socket(
                self.sock, server_hostname=self._real_host
            )

    return _Conn


class _DoHHTTPSHandler(urllib.request.HTTPSHandler):
    """系统 DNS 失效时的备用通道：经 DoH 拿 IP 直连。"""

    def __init__(self, ip_map):
        super().__init__()
        self._ip_map = ip_map

    def https_open(self, req):
        ctx = ssl.create_default_context()  # 对真实域名的完整证书校验
        return self.do_open(_sni_conn_class(self._ip_map), req, context=ctx)


def _direct_call(method, path, headers, body, timeout, opener=None):
    url = API_BASE + path
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    if opener is None:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    with opener.open(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _call(method, path, headers, body=None, timeout=30):
    """底层调用，返回 (status, parsed_json)。

    连接失败时自动兜底：DoH（普通域名→直连 IP）→ 备用传输通道
    （如 App 内 WebView）。HTTPError 直接透出给调用方处理。
    """
    try:
        return _direct_call(method, path, headers, body, timeout)
    except urllib.error.HTTPError:
        raise
    except urllib.error.URLError as e:
        if _is_dns_error(e):
            try:
                ip = _doh_resolve(API_HOST)
                opener = urllib.request.build_opener(
                    _DoHHTTPSHandler({API_HOST: ip})
                )
                return _direct_call(method, path, headers, body, timeout, opener)
            except urllib.error.HTTPError:
                raise
            except CloudflareError:
                raise
            except Exception:
                pass
        if _transport is not None:
            try:
                status, raw = _transport(
                    method, API_BASE + path, dict(headers), body, timeout
                )
                try:
                    return status, json.loads(raw.decode("utf-8"))
                except Exception:
                    raise CloudflareError("备用通道返回了非 JSON 数据")
            except CloudflareError:
                raise
            except Exception as e2:
                raise CloudflareError("备用通道也失败：%s" % e2)
        raise CloudflareError("网络错误：%s" % e.reason)


def _http_error_to_ce(e):
    try:
        body = json.loads(e.read().decode("utf-8"))
    except Exception:
        body = {}
    msgs = "; ".join(
        err.get("message", str(err)) for err in body.get("errors", [])
    ) or ("HTTP %d" % e.code)
    return CloudflareError("Cloudflare API 错误：%s" % msgs)


def _raise_for_status(status, payload):
    if status >= 400:
        msgs = "; ".join(
            err.get("message", str(err)) for err in payload.get("errors", [])
        ) or ("HTTP %d" % status)
        raise CloudflareError("Cloudflare API 错误：%s" % msgs)


def _fail_with_action(action, func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except CloudflareError as e:
        if action and not str(e).startswith(action):
            raise CloudflareError("%s：%s" % (action, e))
        raise


def _req(token, method, path, data=None, content_type=None, timeout=30,
         action=None):
    def _do():
        headers = {"Authorization": "Bearer " + token}
        if content_type:
            headers["Content-Type"] = content_type
        try:
            status, payload = _call(method, path, headers, data, timeout)
        except urllib.error.HTTPError as e:
            raise _http_error_to_ce(e)
        _raise_for_status(status, payload)
        return payload
    return _fail_with_action(action, _do)


def _jreq(auth, method, path, obj=None, timeout=60, action=None):
    """JSON 接口（用于 JWT 凭证的 assets 系列接口）。"""
    def _do():
        body = json.dumps(obj).encode("utf-8") if obj is not None else None
        try:
            status, payload = _call(
                method, path,
                {"Authorization": auth, "Content-Type": "application/json"},
                body, timeout,
            )
        except urllib.error.HTTPError as e:
            raise _http_error_to_ce(e)
        _raise_for_status(status, payload)
        return payload
    return _fail_with_action(action, _do)


def _check(payload, action):
    if not payload.get("success"):
        msgs = "; ".join(
            err.get("message", str(err)) for err in payload.get("errors", [])
        )
        raise CloudflareError("%s失败：%s" % (action, msgs or "未知错误"))
    return payload.get("result")


def list_accounts(token):
    """返回 [{"id":..., "name":...}]。"""
    payload = _req(token, "GET", "/accounts")
    result = _check(payload, "获取账号列表")
    return [{"id": a["id"], "name": a.get("name", "")} for a in result]


def verify_token(token):
    """校验 Token 本身是否有效。返回 {"id","status","expires_on"}。"""
    payload = _req(token, "GET", "/user/tokens/verify")
    return _check(payload, "校验 Token")


def list_projects(token, account_id):
    """列出该账号下的 Pages 项目。"""
    payload = _req(
        token, "GET", "/accounts/%s/pages/projects" % account_id
    )
    return _check(payload, "获取 Pages 项目列表")


def get_project(token, account_id, name):
    """项目不存在时返回 None。"""
    try:
        payload = _req(token, "GET", "/accounts/%s/pages/projects/%s" % (account_id, name))
    except CloudflareError:
        return None
    if not payload.get("success"):
        return None
    return payload.get("result")


def create_project(token, account_id, name):
    """创建直传项目（无 git 集成）。"""
    body = json.dumps(
        {"name": name, "production_branch": "production"}
    ).encode("utf-8")
    payload = _req(
        token, "POST", "/accounts/%s/pages/projects" % account_id,
        data=body, content_type="application/json",
    )
    return _check(payload, "创建 Pages 项目")


def get_or_create_project(token, account_id, name):
    proj = get_project(token, account_id, name)
    if proj is not None:
        return proj, False
    return create_project(token, account_id, name), True


def sanitize_project_name(raw, fallback="mssg-site"):
    """项目名规则：小写字母/数字/连字符，最长 58 字符。"""
    slug = "".join(
        c if (c.isascii() and c.isalnum()) else "-" for c in (raw or "").lower()
    )
    slug = "-".join(p for p in slug.split("-") if p)[:58].strip("-")
    if not slug or not slug[0].isascii() or not slug[0].isalnum():
        slug = fallback
    return slug[:58]


def _encode_multipart(fields):
    """fields: [(字段名, 文件名|None, content_type, bytes)]。"""
    boundary = "mssg" + secrets.token_hex(16)
    buf = bytearray()
    for name, filename, ctype, data in fields:
        buf += ("--%s\r\n" % boundary).encode()
        disp = 'form-data; name="%s"' % name
        if filename:
            disp += '; filename="%s"' % filename
        buf += ("Content-Disposition: %s\r\n" % disp).encode()
        if ctype:
            buf += ("Content-Type: %s\r\n" % ctype).encode()
        buf += b"\r\n" + data + b"\r\n"
    buf += ("--%s--\r\n" % boundary).encode()
    return bytes(buf), "multipart/form-data; boundary=" + boundary


def collect_files(public_dir):
    """收集 public/ 下所有文件 → [("/path", bytes)]。超限文件抛错。"""
    root = Path(public_dir)
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        rel = "/" + p.relative_to(root).as_posix()
        data = p.read_bytes()
        if len(data) > MAX_FILE_SIZE:
            raise CloudflareError("文件过大（>%d MiB）：%s" % (MAX_FILE_SIZE >> 20, rel))
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        out.append((rel, p.name, ctype, data))
    if len(out) > MAX_FILES:
        raise CloudflareError("文件过多（>%d），请精简后重试" % MAX_FILES)
    if not out:
        raise CloudflareError("public/ 为空，请先构建站点")
    return out


def _file_hash(data: bytes, filename: str) -> str:
    """内容哈希（32 位 hex）：sha256(base64(内容) + 扩展名)。

    服务端把哈希当不透明指纹用，只要同一次部署内一致即可。
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    b64 = base64.b64encode(data).decode("ascii")
    return hashlib.sha256((b64 + ext).encode("utf-8")).hexdigest()[:32]


def get_upload_token(token, account_id, project):
    """取文件上传用的 JWT 凭证。"""
    payload = _req(
        token, "GET",
        "/accounts/%s/pages/projects/%s/upload-token" % (account_id, project),
        action="获取上传凭证",
    )
    return _check(payload, "获取上传凭证")["jwt"]


def assets_check_missing(jwt, hashes):
    """返回服务端还没有的哈希列表。jwt 为裸 JWT（不带 Bearer 前缀）。"""
    payload = _jreq("Bearer " + jwt, "POST", "/pages/assets/check-missing",
                    {"hashes": hashes}, action="检查缺失文件")
    return _check(payload, "检查缺失文件")


def assets_upload(jwt, items):
    """items: [(hash, base64内容, content_type)]。jwt 为裸 JWT。"""
    body = [
        {"key": h, "value": b64, "metadata": {"contentType": ct}, "base64": True}
        for h, b64, ct in items
    ]
    payload = _jreq("Bearer " + jwt, "POST", "/pages/assets/upload", body,
                    timeout=120, action="上传文件")
    return _check(payload, "上传文件")


def create_deployment(token, account_id, project, manifest):
    """用 manifest（{"/路径": 哈希}）创建部署；文件已在之前传完。"""
    body, ctype = _encode_multipart([
        ("manifest", None, "application/json",
         json.dumps(manifest).encode("utf-8")),
    ])
    payload = _req(
        token, "POST",
        "/accounts/%s/pages/projects/%s/deployments" % (account_id, project),
        data=body, content_type=ctype, timeout=120, action="创建部署",
    )
    return _check(payload, "创建部署")


def deploy_directory(token, account_id, project, public_dir,
                     on_progress=None):
    """一键部署 public/ 目录。返回 {"url", "project_url", "deployment_id"}。

    协议（同 wrangler）：文件按内容哈希上传 → 发 manifest 建部署。
    on_progress(step:str) 可选回调：collect/upload/wait/done。
    """
    if on_progress:
        on_progress("collect")
    files = collect_files(public_dir)
    hashed = [
        (_file_hash(data, name), rel, name, ctype, data)
        for rel, name, ctype, data in files
    ]
    manifest = {rel: h for h, rel, _n, _c, _d in hashed}

    if on_progress:
        on_progress("upload")
    jwt = get_upload_token(token, account_id, project)
    hashes = [h for h, _r, _n, _c, _d in hashed]
    missing = set(assets_check_missing(jwt, hashes))

    batch, batch_size = [], 0
    for h, rel, name, ctype, data in hashed:
        if h not in missing:
            continue
        b64 = base64.b64encode(data).decode("ascii")
        if batch and (len(batch) >= 500
                      or batch_size + len(b64) > 20 * 1024 * 1024):
            assets_upload(jwt, batch)
            batch, batch_size = [], 0
        batch.append((h, b64, ctype))
        batch_size += len(b64)
    if batch:
        assets_upload(jwt, batch)

    if on_progress:
        on_progress("wait")
    dep = create_deployment(token, account_id, project, manifest)
    dep_id = dep.get("id") or dep.get("uid")
    dep = wait_for_deployment(token, account_id, project, dep_id)
    url, project_url = deployment_urls(dep, project)
    if on_progress:
        on_progress("done")
    return {"url": url, "project_url": project_url, "deployment_id": dep_id}


def list_deployments(token, account_id, project, per_page=5):
    """列出项目的最近部署（用于展示部署状态）。"""
    payload = _req(
        token, "GET",
        "/accounts/%s/pages/projects/%s/deployments?per_page=%d"
        % (account_id, project, per_page),
        action="获取部署记录",
    )
    items = _check(payload, "获取部署记录")
    out = []
    for d in items if isinstance(items, list) else []:
        stage = d.get("latest_stage") or {}
        out.append({
            "id": d.get("id") or d.get("uid"),
            "url": d.get("url", ""),
            "status": stage.get("status", ""),
            "stage": stage.get("name", ""),
            "created_on": d.get("created_on", ""),
            "environment": d.get("environment", ""),
        })
    return out


def get_deployment(token, account_id, project, deployment_id):
    payload = _req(
        token, "GET",
        "/accounts/%s/pages/projects/%s/deployments/%s"
        % (account_id, project, deployment_id),
    )
    return _check(payload, "查询部署状态")


def wait_for_deployment(token, account_id, project, deployment_id,
                        timeout=POLL_TIMEOUT):
    """轮询直到 success/failure，返回最终 deployment dict。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        dep = get_deployment(token, account_id, project, deployment_id)
        last = dep
        stage = dep.get("latest_stage") or {}
        status = stage.get("status")
        if status in ("success", "failure"):
            if status == "failure":
                raise CloudflareError("部署失败，请去 Cloudflare 控制台查看日志")
            return dep
        time.sleep(POLL_INTERVAL)
    raise CloudflareError("部署超时（%ds），请去控制台确认状态" % timeout)


def deployment_urls(deployment, project):
    """(本次部署地址, 生产地址)。"""
    url = (deployment.get("url") or "").rstrip("/")
    if url and not url.startswith("http"):
        url = "https://" + url
    return url, "https://%s.pages.dev" % project
