"""mssg admin：本地内容管理后台。

只监听 127.0.0.1（本机回环），不对外暴露；提供文章的列表/新建/编辑/删除
与一键重建。默认需要一次性 token（启动时打印在 URL 里）才能访问；
不要把它暴露到公网。
"""
from __future__ import annotations

import html
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .frontmatter import split as _split_fm
from .yaml_subset import dumps as _yaml_dumps
from .site import Site

CSS = """
body{font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
max-width:880px;margin:0 auto;padding:24px;color:#1f2937;background:#f9fafb}
a{color:#2563eb}.top{display:flex;justify-content:space-between;align-items:center}
.btn{display:inline-block;padding:.5em 1em;background:#2563eb;color:#fff;border-radius:6px;
text-decoration:none;border:0;cursor:pointer;font-size:14px}
.btn.danger{background:#dc2626}.btn.ghost{background:#e5e7eb;color:#111}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden}
th,td{padding:10px 12px;border-bottom:1px solid #e5e7eb;text-align:left;font-size:14px}
.badge{font-size:12px;padding:2px 8px;border-radius:99px;background:#e5e7eb}
.badge.draft{background:#fde68a}.badge.en{background:#dbeafe}
label{display:block;margin:12px 0 4px;font-weight:600;font-size:14px}
input[type=text],textarea{width:100%;padding:.6em;border:1px solid #d1d5db;border-radius:6px;font-size:14px}
textarea{min-height:320px;font-family:ui-monospace,monospace}
.row{display:flex;gap:12px}.row>div{flex:1}
.msg{padding:10px 14px;border-radius:6px;margin:12px 0;font-size:14px}
.msg.ok{background:#d1fae5}.msg.err{background:#fee2e2;white-space:pre-wrap}
"""

LAYOUT = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>mssg admin</title><style>{css}</style></head>
<body><div class="top"><h1>mssg admin</h1>
<div><a class="btn" href="/new">＋ 新建文章</a>
<form method="post" action="/rebuild" style="display:inline">
<button class="btn ghost" type="submit">重新构建</button></form></div></div>
{msg}{body}<p style="color:#9ca3af;font-size:12px">仅监听 127.0.0.1 · 修改后自动重建</p>
</body></html>"""


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


class AdminApp:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.site = Site(self.root)
        b = self.site.cfg["build"]
        self.content_dir = self.root / b.get("content_dir", "content")

    # -- 文件操作 ------------------------------------------------------

    def _safe_path(self, rel: str) -> Path:
        p = (self.content_dir / rel).resolve()
        try:
            p.relative_to(self.content_dir.resolve())
        except ValueError:
            raise ValueError("非法路径")
        if p.suffix != ".md":
            raise ValueError("只能操作 .md 文件")
        return p

    def _list_pages(self) -> list:
        pages = []
        if self.content_dir.is_dir():
            for md in sorted(self.content_dir.rglob("*.md")):
                rel = md.relative_to(self.content_dir).as_posix()
                try:
                    meta, _ = _split_fm(md.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
                lang, _ = self.site._split_lang(rel)
                pages.append(
                    {
                        "rel": rel,
                        "title": meta.get("title", rel),
                        "date": meta.get("date", ""),
                        "draft": bool(meta.get("draft", False)),
                        "lang": lang,
                    }
                )
        return pages

    def _rebuild(self) -> str:
        try:
            r = Site(self.root).build()
            return "构建成功：%d 个页面" % r.get("pages", 0)
        except Exception:
            return "构建失败：\n" + traceback.format_exc(limit=3)

    # -- 表单 ----------------------------------------------------------

    def _form(self, rel="", meta=None, body="", action="/save") -> str:
        meta = meta or {}
        tags = meta.get("tags", [])
        if isinstance(tags, list):
            tags = ", ".join(str(t) for t in tags)
        cats = meta.get("categories", [])
        if isinstance(cats, list):
            cats = ", ".join(str(c) for c in cats)
        checked = "checked" if meta.get("draft") else ""
        return """
<form method="post" action="{action}">
<input type="hidden" name="rel" value="{rel}">
<label>标题</label><input type="text" name="title" value="{title}" required>
<div class="row"><div><label>日期</label>
<input type="text" name="date" value="{date}" placeholder="2026-10-03"></div>
<div><label>标签（逗号分隔）</label><input type="text" name="tags" value="{tags}"></div>
<div><label>分类（逗号分隔）</label><input type="text" name="categories" value="{cats}"></div></div>
<label><input type="checkbox" name="draft" {checked}> 草稿（不发布）</label>
<label>正文（Markdown）</label><textarea name="body">{body}</textarea>
<p><button class="btn" type="submit">保存</button>
<a class="btn ghost" href="/">取消</a></p></form>""".format(
            action=action,
            rel=_esc(rel),
            title=_esc(meta.get("title", "")),
            date=_esc(meta.get("date", "")),
            tags=_esc(tags),
            cats=_esc(cats),
            checked=checked,
            body=_esc(body),
        )

    def render_index(self, msg="", ok=True) -> str:
        rows = []
        for p in self._list_pages():
            badges = '<span class="badge">%s</span>' % _esc(p["lang"])
            if p["draft"]:
                badges += ' <span class="badge draft">草稿</span>'
            rows.append(
                "<tr><td><a href='/edit?f=%s'>%s</a></td>"
                "<td>%s</td><td>%s</td>"
                "<td><a href='/edit?f=%s'>编辑</a> "
                "<form method='post' action='/delete' style='display:inline' "
                "onsubmit=\"return confirm('删除 %s？')\">"
                "<input type='hidden' name='rel' value='%s'>"
                "<button class='btn danger' type='submit' style='padding:.3em .8em'>删除</button>"
                "</form></td></tr>"
                % (
                    _esc(p["rel"]), _esc(p["title"]), _esc(p["date"]),
                    badges, _esc(p["rel"]), _esc(p["title"]), _esc(p["rel"]),
                )
            )
        body = (
            "<table><tr><th>标题</th><th>日期</th><th>标记</th><th>操作</th></tr>"
            + "".join(rows)
            + "</table>"
            if rows
            else "<p>还没有文章，<a href='/new'>新建一篇</a>吧。</p>"
        )
        m = ""
        if msg:
            m = '<div class="msg %s">%s</div>' % ("ok" if ok else "err", _esc(msg))
        return LAYOUT.format(css=CSS, msg=m, body=body)

    def save_page(self, form: dict) -> str:
        rel = (form.get("rel") or [""])[0].strip()
        title = (form.get("title") or [""])[0].strip()
        date = (form.get("date") or [""])[0].strip()
        tags = [t.strip() for t in (form.get("tags") or [""])[0].split(",") if t.strip()]
        cats = [c.strip() for c in (form.get("categories") or [""])[0].split(",") if c.strip()]
        draft = "draft" in form
        body = (form.get("body") or [""])[0]
        if not rel or not title:
            raise ValueError("标题和文件名不能为空")
        path = self._safe_path(rel)
        meta: dict = {}
        if path.exists():
            old_meta, _ = _split_fm(path.read_text(encoding="utf-8"))
            if isinstance(old_meta, dict):
                meta.update(old_meta)
        meta.update({"title": title})
        if date:
            meta["date"] = date
        elif "date" not in meta:
            from datetime import date as _date

            meta["date"] = _date.today().isoformat()
        if tags:
            meta["tags"] = tags
        elif "tags" in meta:
            del meta["tags"]
        if cats:
            meta["categories"] = cats
        elif "categories" in meta:
            del meta["categories"]
        if draft:
            meta["draft"] = True
        else:
            meta.pop("draft", None)
        fm = _yaml_dumps(meta)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\n" + fm + "---\n" + body.lstrip("\n"), encoding="utf-8")
        return rel


class _Handler(BaseHTTPRequestHandler):
    app: AdminApp = None  # type: ignore
    token: str | None = None  # 为 None 时不鉴权

    def log_message(self, *a):
        pass

    def _authorized(self) -> bool:
        """token 鉴权：query ?token= 或 Cookie mssg_token。"""
        if not self.token:
            return True
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if (q.get("token") or [""])[0] == self.token:
            return True
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            if part.strip() == "mssg_token=" + self.token:
                return True
        return False

    def _deny(self):
        self._send(
            "<h1>403</h1><p>需要 token：用启动时打印的完整 URL 访问。</p>", 403
        )

    def _send(self, html_text: str, code=200, set_cookie: bool = False):
        data = html_text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if set_cookie and self.token:
            self.send_header(
                "Set-Cookie",
                "mssg_token=%s; Path=/; HttpOnly; SameSite=Lax" % self.token,
            )
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, to: str):
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    def _read_form(self) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(n).decode("utf-8", "replace") if n else ""
        return parse_qs(raw, keep_blank_values=True)

    def do_GET(self):
        if not self._authorized():
            self._deny()
            return
        u = urlparse(self.path)
        try:
            if u.path == "/":
                # query 带 token 进来时种下 cookie，后续免带
                self._send(self.app.render_index(), set_cookie=True)
            elif u.path == "/new":
                inner = self.app._form(rel="post/untitled.md").replace(
                    '<input type="hidden" name="rel" value="post/untitled.md">',
                    "<label>文件名（content/ 下相对路径，如 post/hello.md）</label>"
                    '<input type="text" name="rel" value="post/untitled.md" required>',
                )
                page = LAYOUT.format(
                    css=CSS, msg="", body="<h2>新建文章</h2>" + inner
                )
                self._send(page)
            elif u.path == "/edit":
                q = parse_qs(u.query)
                rel = (q.get("f") or [""])[0]
                path = self.app._safe_path(rel)
                meta, body = _split_fm(path.read_text(encoding="utf-8"))
                page = LAYOUT.format(
                    css=CSS, msg="",
                    body="<h2>编辑 %s</h2>" % _esc(rel)
                    + self.app._form(rel=rel, meta=meta, body=body),
                )
                self._send(page)
            else:
                self._send("404", 404)
        except Exception as e:
            self._send(self.app.render_index("出错：%s" % e, ok=False))

    def do_POST(self):
        if not self._authorized():
            self._deny()
            return
        u = urlparse(self.path)
        try:
            form = self._read_form()
            if u.path == "/save":
                rel = self.app.save_page(form)
                msg = "已保存 %s；%s" % (rel, self.app._rebuild())
                self._send(self.app.render_index(msg))
            elif u.path == "/delete":
                rel = (form.get("rel") or [""])[0]
                path = self.app._safe_path(rel)
                if path.exists():
                    path.unlink()
                msg = "已删除 %s；%s" % (rel, self.app._rebuild())
                self._send(self.app.render_index(msg))
            elif u.path == "/rebuild":
                msg = self.app._rebuild()
                self._send(self.app.render_index(msg, ok="失败" not in msg))
            else:
                self._send("404", 404)
        except Exception as e:
            self._send(self.app.render_index("出错：%s" % e, ok=False))


def run(root: str | Path, port: int = 8902, token: str | None = None,
        no_auth: bool = False) -> None:
    """启动本地管理后台（仅 127.0.0.1）。

    默认生成一次性 token 并打印在 URL 里；--token 可指定固定 token，
    --no-auth 关闭鉴权（仅自己电脑上用）。
    """
    import secrets

    if no_auth:
        use_token = None
        print("警告：鉴权已关闭，仅在自己电脑上使用！")
    else:
        use_token = token or secrets.token_urlsafe(16)
    _Handler.app = AdminApp(root)
    _Handler.token = use_token
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    url = "http://127.0.0.1:%d/" % port
    if use_token:
        url += "?token=" + use_token
    print("mssg admin 运行在 %s （仅本机可访问，Ctrl+C 退出）" % url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
