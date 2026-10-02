"""mssg 命令行入口：new / build / serve。"""

from __future__ import annotations

import argparse
import functools
import http.server
import os
import threading
import time

from .site import Site, new_site


def _cmd_new(args) -> int:
    try:
        root = new_site(args.name)
    except FileExistsError as e:
        print("错误：%s" % e)
        return 1
    print("已创建站点：%s" % root)
    print("  cd %s && mssg build && mssg serve" % root)
    return 0


def _cmd_build(args) -> int:
    try:
        site = Site(".", config=args.config)
        result = site.build(force=args.force, include_drafts=args.drafts)
    except Exception as e:
        print("构建失败：%s" % e)
        return 1
    b = site.cfg["build"]
    print(
        "构建完成：%d 个页面，输出到 %s/%s%s"
        % (
            result["pages"],
            ".",
            b["output_dir"],
            "（有更新）" if result["rebuilt"] else "（无变化，增量跳过）",
        )
    )
    return 0


def _snapshot(paths: list) -> dict:
    """对监听路径做 (mtime, size) 快照。"""
    snap = {}
    for base in paths:
        if os.path.isdir(base):
            for dp, _, fns in os.walk(base):
                for fn in fns:
                    p = os.path.join(dp, fn)
                    try:
                        st = os.stat(p)
                    except OSError:
                        continue
                    snap[p] = (st.st_mtime, st.st_size)
        elif os.path.isfile(base):
            try:
                st = os.stat(base)
            except OSError:
                continue
            snap[base] = (st.st_mtime, st.st_size)
    return snap


def _watch_and_rebuild(site: Site, args, stop_event: threading.Event) -> None:
    """轮询监听内容/模板/静态资源/配置变化，变化时自动重建。"""
    b = site.cfg["build"]
    watched = [
        os.path.join(str(site.root), b["content_dir"]),
        os.path.join(str(site.root), b["template_dir"]),
        os.path.join(str(site.root), b["static_dir"]),
        os.path.join(str(site.root), args.config),
    ]
    last = _snapshot(watched)
    while not stop_event.wait(0.5):
        cur = _snapshot(watched)
        if cur == last:
            continue
        last = cur
        now = time.strftime("%H:%M:%S")
        try:
            result = site.build(include_drafts=args.drafts)
            print(
                "[%s] 检测到变化，重建完成：%d 个页面" % (now, result["pages"]),
                flush=True,
            )
        except Exception as e:  # noqa: BLE001
            # 构建失败（如模板语法错误）不退出，继续监听等用户修复
            print("[%s] 构建失败：%s（继续监听）" % (now, e), flush=True)


def _cmd_serve(args) -> int:
    try:
        site = Site(".", config=args.config)
        site.build(include_drafts=args.drafts)
    except Exception as e:
        print("构建失败：%s" % e)
        return 1
    output_dir = os.path.join(".", site.cfg["build"]["output_dir"])
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=output_dir
    )
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    except OSError as e:
        print("错误：无法监听端口 %d（%s）" % (args.port, e))
        return 1
    print("本地预览：http://127.0.0.1:%d/ （Ctrl-C 退出）" % args.port)
    stop_event = threading.Event()
    watcher = None
    if not args.no_watch:
        print("正在监听文件变化，自动重建…")
        watcher = threading.Thread(
            target=_watch_and_rebuild, args=(site, args, stop_event), daemon=True
        )
        watcher.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
    return 0


def main() -> int:
    from . import __version__

    parser = argparse.ArgumentParser(
        prog="mssg", description="极简零依赖静态站点生成器"
    )
    parser.add_argument(
        "-V", "--version", action="version", version="mssg %s" % __version__
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new", help="新建站点脚手架")
    p_new.add_argument("name", help="站点目录名")
    p_new.set_defaults(func=_cmd_new)

    p_build = sub.add_parser("build", help="构建站点")
    p_build.add_argument("-c", "--config", default="mssg.toml")
    p_build.add_argument("--force", action="store_true", help="强制全量重建")
    p_build.add_argument("--drafts", action="store_true", help="包含草稿（draft: true）")
    p_build.set_defaults(func=_cmd_build)

    p_serve = sub.add_parser("serve", help="构建并本地预览")
    p_serve.add_argument("-c", "--config", default="mssg.toml")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--drafts", action="store_true", help="包含草稿（draft: true）")
    p_serve.add_argument("--no-watch", action="store_true", help="关闭文件监听自动重建")
    p_serve.set_defaults(func=_cmd_serve)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
