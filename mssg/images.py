"""静态图片优化（Pillow）：压缩 + 按宽度缩放，失败回退普通拷贝。"""
from __future__ import annotations

import shutil
from pathlib import Path

IMG_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMG_SUFFIXES


def copy_static_file(src: Path, dst: Path, max_w: int, quality: int) -> None:
    """拷贝静态文件；图片按配置压缩/缩放，失败时回退普通拷贝。

    max_w <= 0 表示不缩放只压缩。
    """
    if is_image(src):
        try:
            from PIL import Image

            im = Image.open(src)
            if max_w and im.width > max_w:
                im = im.resize(
                    (max_w, max(1, round(im.height * max_w / im.width))),
                    Image.LANCZOS,
                )
            dst.parent.mkdir(parents=True, exist_ok=True)
            suf = src.suffix.lower()
            if suf in (".jpg", ".jpeg"):
                if im.mode in ("RGBA", "LA", "P"):
                    im = im.convert("RGB")
                im.save(dst, quality=int(quality or 82), optimize=True)
            elif suf == ".png":
                im.save(dst, optimize=True)
            else:
                im.save(dst)
            return
        except Exception:
            pass
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
