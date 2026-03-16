FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir ".[frontend]"

ENV BACKEND_URL=http://backend:8000

WORKDIR /workspace/src/frontend
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
