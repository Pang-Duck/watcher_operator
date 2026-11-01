FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .[operator] \
    && useradd --system --uid 10001 --create-home operator

USER 10001:10001

ENTRYPOINT ["python", "-m", "watcher_operator"]
