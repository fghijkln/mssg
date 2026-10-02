"""站点源码备份与恢复。

backup_site(site_dir, dest=None) -> zip 路径：
    把 mssg.toml、content/、static/、data/、templates/ 打成一个 ZIP
    （扁平结构，解压即站点目录，可换机恢复）。
    默认排除：public/（构建产物，可重新生成）、.git/、__pycache__/、
    .mssg_cf.json（Cloudflare Token，换机后重新连接即可）。

restore_site(zip_path, dest_dir) -> 站点目录：解压恢复（含 zip-slip 防护）。
"""

import datetime
import zipfile
from pathlib import Path

INCLUDE_FILES = ("mssg.toml",)
INCLUDE_DIRS = ("content", "static", "data", "templates")
EXCLUDE_DIR_NAMES = {
    "public", ".git", "__pycache__", ".hg", ".svn", "node_modules",
}
EXCLUDE_FILE_NAMES = {".mssg_cf.json", ".DS_Store"}


def _iter_source_files(site: Path):
    for name in INCLUDE_FILES:
        p = site / name
        if p.is_file():
            yield p
    for dirname in INCLUDE_DIRS:
        root = site / dirname
        if not root.is_dir():
            continue
        for f in sorted(root.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(site)
            if f.name in EXCLUDE_FILE_NAMES:
                continue
            if any(part in EXCLUDE_DIR_NAMES for part in rel.parts):
                continue
            yield f


def backup_site(site_dir, dest=None):
    """打包站点源码为 ZIP，返回 zip 路径（str）。"""
    site = Path(site_dir)
    if not (site / "mssg.toml").is_file():
        raise ValueError("不是 mssg 站点目录：%s" % site_dir)
    if dest is None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = site.parent / ("mssg-backup-%s.zip" % stamp)
    dest = Path(dest)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in _iter_source_files(site):
            zf.write(f, f.relative_to(site).as_posix())
    return str(dest)


def restore_site(zip_path, dest_dir):
    """从备份 ZIP 恢复站点到 dest_dir，返回站点目录（str）。"""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            target = (dest_resolved / info.filename).resolve()
            if target != dest_resolved and dest_resolved not in target.parents:
                raise ValueError("备份中包含非法路径：%s" % info.filename)
        zf.extractall(dest_resolved)
    if not (dest_resolved / "mssg.toml").is_file():
        raise ValueError("该 ZIP 不是有效的 mssg 站点备份（缺少 mssg.toml）")
    return str(dest_resolved)
