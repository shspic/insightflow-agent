from datetime import datetime, timezone


def utcnow() -> datetime:
    """返回不带时区的 UTC 当前时间。

    历史数据库列、既有比较逻辑和已存储的 SQLite 时间戳全部使用 naive UTC。
    这里显式基于 timezone-aware 的 UTC 时间再去掉 tzinfo，既避免
    `datetime.utcnow()` 的弃用告警，又保持与现有数据完全一致的 naive UTC 语义。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
