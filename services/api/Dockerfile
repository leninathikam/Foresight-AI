FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY packages ./packages
COPY services ./services
COPY scripts ./scripts
COPY artifacts ./artifacts

RUN uv sync --frozen --no-dev \
 && uv run python -c "from foresight.artifacts import load_or_train_bundle; load_or_train_bundle()"

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "foresight_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
