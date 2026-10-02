"""Cloudflare Pages 直接部署（Direct Upload API）。

只用 Python 标准库（urllib），无第三方依赖。流程：

1. ``list_accounts(token)`` → 账号列表（取第一个即可）
2. ``get_or_create_project(token, account_id, name)`` → 项目不存在则创建
3. ``deploy_directory(token, account_id, project, public_dir)``
   → multipart 上传 public/ 下所有文件 → 轮询部署状态 → 返回线上地址

Token 权限：Cloudflare Pages → Edit（在
https://dash.cloudflare.com/profile/api-tokens 创建自定义 Token）。
"""

import json
import mimetypes
import os
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://api.cloudflare.com/client/v4"
MAX_FILE_SIZE = 25 * 1024 * 1024  # Cloudflare 单文件上限 25 MiB
MAX_FILES = 20000  # Cloudflare 单次部署文件数上限
POLL_INTERVAL = 3
POLL_TIMEOUT = 180


class CloudflareError(Exception):
    """Cloudflare API 返回 success=false 或网络层失败。"""


def _req(token, method, path, data=None, content_type=None, timeout=30):
    url = API_BASE + path
    headers = {"Authorization": "Bearer " + token}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {}
        msgs = "; ".join(
            err.get("message", str(err)) for err in body.get("errors", [])
        ) or ("HTTP %d" % e.code)
        raise CloudflareError("Cloudflare API 错误：%s" % msgs)
    except urllib.error.URLError as e:
        raise CloudflareError("网络错误：%s" % e.reason)


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


def create_deployment(token, account_id, project, files):
    """上传文件并创建部署，返回 deployment dict。"""
    body, ctype = _encode_multipart(files)
    payload = _req(
        token, "POST",
        "/accounts/%s/pages/projects/%s/deployments" % (account_id, project),
        data=body, content_type=ctype, timeout=120,
    )
    return _check(payload, "创建部署")


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


def deploy_directory(token, account_id, project, public_dir,
                     on_progress=None):
    """一键部署 public/ 目录。返回 {"url", "project_url", "deployment_id"}。

    on_progress(step:str) 可选回调：collect/upload/wait/done。
    """
    if on_progress:
        on_progress("collect")
    files = collect_files(public_dir)
    if on_progress:
        on_progress("upload")
    dep = create_deployment(token, account_id, project, files)
    dep_id = dep.get("id") or dep.get("uid")
    if on_progress:
        on_progress("wait")
    dep = wait_for_deployment(token, account_id, project, dep_id)
    url, project_url = deployment_urls(dep, project)
    if on_progress:
        on_progress("done")
    return {"url": url, "project_url": project_url, "deployment_id": dep_id}
