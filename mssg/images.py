"""静态图片优化（Pillow 可选）：压缩 + 按宽度缩放，失败回退普通拷贝。"""
from __future__ import annotations

import hashlib
import os
import shutil
import warnings
from pathlib import Path

IMG_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def copy_file_writable(src: Path, dst: Path) -> None:
    """拷贝文件到构建输出目录。

    不用 shutil.copy2：它会把源文件的权限位（含只读）带到输出，
    下次构建覆盖只读输出时就 PermissionError（手机上必现，
    Chaquopy 解压的包文件就是只读的）。同时修复旧版本留下的
    只读输出文件。
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        try:
            os.chmod(dst, 0o644)
        except OSError:
            pass
    shutil.copyfile(src, dst)
    try:
        os.chmod(dst, 0o644)
    except OSError:
        pass

_PIL = None  # None=未检测；False=未安装；否则为 PIL.Image 模块
_warned_no_pil = False


def _pil():
    """取 PIL.Image；未安装时警告一次并返回 None（调用方回退普通拷贝）。"""
    global _PIL, _warned_no_pil
    if _PIL is None:
        try:
            from PIL import Image

            _PIL = Image
        except ImportError:
            _PIL = False
    if _PIL is False and not _warned_no_pil:
        _warned_no_pil = True
        warnings.warn(
            "Pillow 未安装，图片将直接拷贝不再压缩/缩放；"
            'pip install "mssg[images]" 可恢复'
        )
    return _PIL or None


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMG_SUFFIXES


def copy_static_file(src: Path, dst: Path, max_w: int, quality: int) -> None:
    """拷贝静态文件；图片按配置压缩/缩放，失败时回退普通拷贝。

    max_w <= 0 表示不缩放只压缩。
    """
    if is_image(src):
        Image = _pil()
        if Image is not None:
            try:
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
    copy_file_writable(src, dst)


def _sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def place_image(
    src: Path,
    dst: Path,
    max_w: int,
    quality: int,
    cache: dict,
    cache_key: str,
) -> None:
    """按需处理并放置一张图片（源指纹 + 配置不变且输出存在则跳过）。"""
    sig = "%s|%s|%s" % (_sha1_file(src), max_w, quality)
    if cache.get(cache_key) == sig and dst.exists():
        return
    copy_static_file(src, dst, max_w, quality)
    cache[cache_key] = sig
