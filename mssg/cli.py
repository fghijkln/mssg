"""mssg 命令行入口：new / build / serve。"""

from __future__ import annotations

import argparse
import functools
import http.server
import os

from .site import Site, new_site


def _cmd_new(args) -> int:
    root = new_site(args.name)
    print("已创建站点：%s" % root)
    print("  cd %s && mssg build && mssg serve" % root)
    return 0


def _cmd_build(args) -> int:
    site = Site(".", config=args.config)
    result = site.build(force=args.force)
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


def _cmd_serve(args) -> int:
    site = Site(".", config=args.config)
    site.build()
    output_dir = os.path.join(".", site.cfg["build"]["output_dir"])
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=output_dir
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print("本地预览：http://127.0.0.1:%d/ （Ctrl-C 退出）" % args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="mssg", description="极简零依赖静态站点生成器"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new", help="新建站点脚手架")
    p_new.add_argument("name", help="站点目录名")
    p_new.set_defaults(func=_cmd_new)

    p_build = sub.add_parser("build", help="构建站点")
    p_build.add_argument("-c", "--config", default="mssg.toml")
    p_build.add_argument("--force", action="store_true", help="强制全量重建")
    p_build.set_defaults(func=_cmd_build)

    p_serve = sub.add_parser("serve", help="构建并本地预览")
    p_serve.add_argument("-c", "--config", default="mssg.toml")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.set_defaults(func=_cmd_serve)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
