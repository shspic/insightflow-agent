FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OCR_LANG=chi_sim+eng \
    MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-noto-cjk \
        libfreetype6 \
        libglib2.0-0 \
        libgl1 \
        libgomp1 \
        libjpeg62-turbo \
        libpng16-16 \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
        tesseract-ocr-eng \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

RUN groupadd --gid 10001 insightflow \
    && useradd --uid 10001 --gid insightflow --create-home --shell /usr/sbin/nologin insightflow \
    && mkdir -p /app/data /app/storage/uploads /app/storage/charts /app/storage/reports \
        /app/backups /app/logs /tmp/matplotlib \
    && chown -R insightflow:insightflow /app /tmp/matplotlib

COPY --chown=insightflow:insightflow app ./app
COPY --chown=insightflow:insightflow alembic ./alembic
COPY --chown=insightflow:insightflow alembic.ini ./
COPY --chown=insightflow:insightflow docker-entrypoint.sh ./

# 固化入口可执行权限：不依赖 Windows 文件权限或本地 build context 权限位
RUN chmod 0555 /app/docker-entrypoint.sh

USER insightflow

EXPOSE 8000

# 启动前安全执行 Alembic 迁移（幂等），再启动实际命令。
# 覆盖 CMD 可运行 worker 等其他入口，迁移始终先执行。
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "-m", "app.cli.run_api"]
