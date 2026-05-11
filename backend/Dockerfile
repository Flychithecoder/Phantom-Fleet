FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY phantom_fleet ./phantom_fleet
COPY migrations ./migrations
COPY scripts ./scripts

RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["uvicorn", "phantom_fleet.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
