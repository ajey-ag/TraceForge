FROM docker:29.6.2-cli AS dockercli
FROM python:3.12.10-slim
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv
WORKDIR /app
COPY . .
RUN uv sync --frozen --no-editable
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
CMD ["uvicorn", "apps.runner.main:app", "--host", "0.0.0.0", "--port", "8765"]
