import uvicorn

from app.core.config import settings


def main() -> None:
    """以单进程和精确代理白名单启动生产 API。"""
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        workers=1,
        reload=False,
        proxy_headers=settings.trust_proxy_headers,
        forwarded_allow_ips=settings.trusted_proxy_ips or "127.0.0.1",
        timeout_graceful_shutdown=max(1, settings.api_graceful_shutdown_seconds),
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
