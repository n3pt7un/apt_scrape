FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl git \
    libgtk-3-0 libdbus-glib-1-2 libxt6t64 libx11-xcb1 \
    libxcomposite1 libxcursor1 libxdamage1 libxfixes3 \
    libxi6 libxrandr2 libxrender1 libxss1 libxtst6 \
    libasound2t64 libpangocairo-1.0-0 libpango-1.0-0 \
    libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 libnss3 \
    libgdk-pixbuf-2.0-0 fonts-liberation libgbm1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir ".[backend]"

# Install camoufox browser binary
RUN python -m camoufox fetch

ENV PYTHONPATH=/workspace/src
ENV DB_PATH=/data/app.db
ENV PREFERENCES_FILE=/data/preferences.txt

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
