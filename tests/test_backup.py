"""v0.14.0: 站点源码备份与恢复。"""

import zipfile

import pytest

from mssg.backup import backup_site, restore_site
from mssg.scaffold import new_site


@pytest.fixture()
def site(tmp_path):
    new_site(str(tmp_path / "s"))
    return tmp_path / "s"


def _names(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        return sorted(zf.namelist())


def test_backup_includes_source(site, tmp_path):
    z = backup_site(str(site), dest=str(tmp_path / "b.zip"))
    names = _names(z)
    assert "mssg.toml" in names
    assert "content/hello.md" in names
    assert "data/links.json" in names


def test_backup_excludes_build_and_secrets(site, tmp_path):
    (site / "public").mkdir(exist_ok=True)
    (site / "public" / "index.html").write_text("x", encoding="utf-8")
    (site / ".git").mkdir(exist_ok=True)
    (site / ".git" / "config").write_text("x", encoding="utf-8")
    (site / ".mssg_cf.json").write_text('{"token": "secret"}', encoding="utf-8")
    (site / "templates").mkdir(exist_ok=True)
    (site / "templates" / "custom.html").write_text("x", encoding="utf-8")
    names = _names(backup_site(str(site), dest=str(tmp_path / "b.zip")))
    assert not any(n.startswith("public/") for n in names)
    assert not any(n.startswith(".git/") for n in names)
    assert ".mssg_cf.json" not in names
    assert "templates/custom.html" in names  # 站点覆盖模板要备份


def test_backup_rejects_non_site(tmp_path):
    with pytest.raises(ValueError):
        backup_site(str(tmp_path), dest=str(tmp_path / "b.zip"))


def test_restore_roundtrip(site, tmp_path):
    z = backup_site(str(site), dest=str(tmp_path / "b.zip"))
    dest = restore_site(z, str(tmp_path / "r"))
    assert (tmp_path / "r" / "mssg.toml").is_file()
    assert (tmp_path / "r" / "content" / "hello.md").is_file()
    assert dest == str((tmp_path / "r").resolve())


def test_restore_rejects_zip_slip(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../../evil.txt", "x")
    with pytest.raises(ValueError):
        restore_site(str(z), str(tmp_path / "r"))


def test_restore_rejects_non_backup(tmp_path):
    z = tmp_path / "plain.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("readme.txt", "x")
    with pytest.raises(ValueError):
        restore_site(str(z), str(tmp_path / "r"))
