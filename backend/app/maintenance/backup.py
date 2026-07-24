import argparse
import hashlib
import json
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from app.core.config import BACKEND_DIR, settings


def create_backup(output_root: Path | None = None) -> dict:
    source_db = _sqlite_database_path()
    if not source_db.is_file():
        raise RuntimeError("SQLite 数据库文件不存在")
    root = output_root or _path(settings.backup_dir)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    destination = root / f"insightflow-backup-{timestamp}"
    if destination.exists():
        raise RuntimeError("备份目标已存在")
    destination.mkdir(parents=True, exist_ok=False)
    database_backup = destination / "database.sqlite3"
    with sqlite3.connect(source_db) as source, sqlite3.connect(database_backup) as target:
        source.backup(target)
        integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError("备份数据库一致性检查失败")
    storage_archive = destination / "storage.zip"
    storage_root = BACKEND_DIR / "storage"
    with zipfile.ZipFile(storage_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if storage_root.is_dir():
            for path in storage_root.rglob("*"):
                if path.is_file() and path.name != ".env":
                    archive.write(path, path.relative_to(BACKEND_DIR).as_posix())
    manifest = {
        "created_at": datetime.utcnow().isoformat(),
        "database_revision_hint": "执行 alembic current 确认",
        "files": {
            database_backup.name: {
                "size_bytes": database_backup.stat().st_size,
                "sha256": _checksum(database_backup),
            },
            storage_archive.name: {
                "size_bytes": storage_archive.stat().st_size,
                "sha256": _checksum(storage_archive),
            },
        },
        "excluded": [".env", "API Key", "Session 明文 Token"],
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"backup_dir": str(destination), "manifest": manifest}


def verify_backup(backup_dir: Path) -> dict:
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("备份 manifest 不存在")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, expected in manifest["files"].items():
        path = backup_dir / name
        if not path.is_file() or _checksum(path) != expected["sha256"]:
            raise RuntimeError(f"备份文件校验失败：{name}")
    with sqlite3.connect(backup_dir / "database.sqlite3") as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError("备份数据库一致性校验失败")
    return {"status": "verified", "file_count": len(manifest["files"])}


def _sqlite_database_path() -> Path:
    prefix = "sqlite:///"
    if not settings.database_url.startswith(prefix):
        raise RuntimeError("当前备份工具只支持 SQLite 阶段")
    value = unquote(settings.database_url.removeprefix(prefix))
    path = Path(value)
    return path if path.is_absolute() else BACKEND_DIR / path


def _path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else BACKEND_DIR / path


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="创建或校验 InsightFlow SQLite 备份")
    parser.add_argument("--output-root")
    parser.add_argument("--verify")
    args = parser.parse_args()
    if args.verify:
        print(verify_backup(Path(args.verify)))
    else:
        print(create_backup(Path(args.output_root) if args.output_root else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
