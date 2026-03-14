FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl git && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Install the apt_scrape package (editable) from repo root (mounted as /workspace)
COPY requirements.txt /tmp/apt_requirements.txt
RUN pip install --no-cache-dir -r /tmp/apt_requirements.txt

# Install camoufox browser binary
RUN pip install camoufox && python -m camoufox fetch

# Install backend dependencies
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

ENV PYTHONPATH=/workspace
ENV DB_PATH=/data/app.db
ENV PREFERENCES_FILE=/data/preferences.txt

WORKDIR /workspace
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
