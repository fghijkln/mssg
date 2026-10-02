"""主题发现：内置主题位于 mssg/themes/<name>/（templates/ + static/）。"""
from __future__ import annotations

from pathlib import Path

_THEMES_DIR = Path(__file__).parent / "themes"


def available_themes() -> list:
    """可用主题名列表。"""
    if not _THEMES_DIR.is_dir():
        return []
    return sorted(p.name for p in _THEMES_DIR.iterdir() if p.is_dir())


def theme_dirs(theme: str) -> tuple:
    """主题的 (templates_dir, static_dir)；不存在时报 ValueError。"""
    theme = theme or "company"
    tdir = _THEMES_DIR / theme
    if not tdir.is_dir():
        raise ValueError(
            "未知主题 %r，可用主题：%s（mssg.toml 里改 [site] theme）"
            % (theme, ", ".join(available_themes()) or "无")
        )
    return tdir / "templates", tdir / "static"
