"""front matter 解析（零依赖，基于 mssg.yaml_subset）。

文件开头用 --- 包裹的 YAML 子集块：
    ---
    title: 你好
    date: 2026-10-02
    tags: [a, b]
    draft: false
    ---
"""
from __future__ import annotations

from .yaml_subset import loads as _yaml_loads


def split(text: str) -> tuple[dict, str]:
    """分离 front matter 与正文，返回 (meta, body)。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() in ("---", "..."):
            end = idx
            break
    if end is None:
        return {}, text
    meta = _yaml_loads("\n".join(lines[1:end]))
    if not isinstance(meta, dict):
        meta = {}
    block = "\n".join(lines[1:end])
    if not meta and any(
        ln.strip() and not ln.strip().startswith("#")
        for ln in block.split("\n")
    ):
        # 块里没有任何有效键：这不是 front matter，别吞掉正文
        return {}, text
    return meta, "\n".join(lines[end + 1 :])
