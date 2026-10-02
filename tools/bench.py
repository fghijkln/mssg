"""mssg 构建性能基准：生成 N 篇文章，测量冷构建/热重建/单页改动耗时。

用法：python tools/bench.py [--pages 1000] [--keep DIR]
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mssg.site import Site, new_site

BODY = """\
---
title: 文章 %d
date: 2026-%02d-%02d
tags: [tag%d, 性能]
---

# 文章 %d

这是第 %d 篇性能测试文章，用于测量 mssg 在大站下的构建速度。

## 小节

正文内容正文内容。**加粗**与`代码`混合排版，顺带一张表格：

| 列 A | 列 B |
|------|------|
| a%d   | b%d   |

```python
def hello_%d():
    return "world"
```

> 引用块引用块引用块。
"""


def make_site(root: Path, n: int) -> None:
    new_site(root)
    content = root / "content"
    for i in range(n):
        (content / ("p%04d.md" % i)).write_text(
            BODY % (i, (i % 12) + 1, (i % 28) + 1, i % 20, i, i, i, i, i),
            encoding="utf-8",
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=1000)
    ap.add_argument("--keep", default="")
    args = ap.parse_args()

    tmp = Path(args.keep) if args.keep else Path(tempfile.mkdtemp(prefix="mssg-bench-"))
    root = tmp / "site"
    if root.exists():
        shutil.rmtree(root)
    t0 = time.perf_counter()
    make_site(root, args.pages)
    t_gen = time.perf_counter() - t0

    t0 = time.perf_counter()
    r1 = Site(root).build()
    t_cold = time.perf_counter() - t0

    t0 = time.perf_counter()
    r2 = Site(root).build()
    t_warm = time.perf_counter() - t0

    # 改一页
    (root / "content" / "p0000.md").write_text(
        (root / "content" / "p0000.md").read_text(encoding="utf-8") + "\n改动一行。\n",
        encoding="utf-8",
    )
    t0 = time.perf_counter()
    r3 = Site(root).build()
    t_one = time.perf_counter() - t0

    print("站点：%s" % root)
    print("生成 %d 页源文件：%.2fs" % (args.pages, t_gen))
    print("冷构建（%d 页）：%.2fs" % (r1["pages"], t_cold))
    print("热重建（无改动）：%.2fs rebuilt=%s" % (t_warm, r2["rebuilt"]))
    print("单页改动重建：%.2fs rebuilt=%s" % (t_one, r3["rebuilt"]))
    if not args.keep:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
