FROM python:3.14-slim AS dependencies
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.14-slim
ARG VERSION=local
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_VERSION=${VERSION} DATABASE_PATH=/data/orders.db
WORKDIR /app
COPY --from=dependencies /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt && rm -rf /wheels \
    && mkdir /data && chown 10001:10001 /data
COPY --chown=10001:10001 app.py .
COPY --chown=10001:10001 migrations ./migrations
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=6 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/ready', timeout=2)"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log"]
