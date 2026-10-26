FROM python:3.12.10-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv
WORKDIR /app
COPY . .
RUN uv sync --frozen --extra dev --no-editable \
    && useradd --uid 10001 --create-home traceforge \
    && mkdir -p /data/artifacts && chown -R traceforge:traceforge /data
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER traceforge
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
