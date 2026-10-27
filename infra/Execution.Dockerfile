FROM python:3.12.10-slim
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv
WORKDIR /opt/project
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --extra dev --no-install-project
COPY infra/executor.py /opt/executor.py
COPY infra/checks /opt/checks
ENV PATH="/opt/project/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
WORKDIR /workspace
ENTRYPOINT ["python", "/opt/executor.py"]
