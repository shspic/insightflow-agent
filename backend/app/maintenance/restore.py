import argparse
import shutil
from pathlib import Path

from app.maintenance.backup import verify_backup


def restore_database(backup_dir: Path, destination: Path) -> dict:
    verify_backup(backup_dir)
    if destination.exists():
        raise RuntimeError("恢复目标已存在；工具默认不会覆盖现有数据库")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(backup_dir / "database.sqlite3", destination)
    return {"status": "restored", "database": str(destination)}


def main() -> int:
    parser = argparse.ArgumentParser(description="安全恢复 InsightFlow SQLite 数据库副本")
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    print(restore_database(Path(args.backup_dir), Path(args.destination)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
