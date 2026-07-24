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

USER insightflow

EXPOSE 8000

CMD ["python", "-m", "app.cli.run_api"]
