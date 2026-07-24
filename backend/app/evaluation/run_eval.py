import argparse
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.evaluation.runner import export_failures, run_evaluation, run_response


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 InsightFlow V2 自动评估")
    parser.add_argument("--dataset", default="v2-core")
    parser.add_argument("--mode", choices=["deterministic", "model"], default="deterministic")
    parser.add_argument("--category")
    parser.add_argument("--allow-model", action="store_true")
    parser.add_argument("--database-url")
    parser.add_argument("--export-failures")
    args = parser.parse_args()
    if args.mode == "model" and not args.allow_model:
        parser.error("model 模式必须显式提供 --allow-model")
    if args.mode == "model":
        parser.error("当前阶段 CLI 仅实现 deterministic；未调用真实 DeepSeek")
    database_url = args.database_url or os.getenv(
        "EVALUATION_DATABASE_URL", "sqlite:///./data/evaluation.db"
    )
    if database_url == os.getenv("DATABASE_URL"):
        parser.error("评估数据库不得与真实业务数据库相同")
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with session_factory() as db:
        run = run_evaluation(
            db,
            dataset_name=args.dataset,
            mode=args.mode,
            category=args.category,
        )
        payload = run_response(run)
        print(payload)
        if args.export_failures:
            count = export_failures(db, run.id, Path(args.export_failures))
            print({"failure_export_count": count, "output": args.export_failures})
        return 0 if run.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
