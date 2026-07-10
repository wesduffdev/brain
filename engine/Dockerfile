# Engine image for the situated-being simulation.
# Lean Python base; installs engine/requirements.txt only (kept minimal per
# slice — later slices add their own deps). Build context is ./engine.
FROM python:3.12-slim

# Predictable Python runtime inside the container.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install dependencies first so this layer caches across app-code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application. At runtime docker-compose bind-mounts ./engine over /app
# for live edits; this COPY keeps the image runnable on its own.
COPY . .

# Default to the demo tick-loop so the image runs today (V0-5). The compose
# file overrides this per service; V0-6 switches the engine command to uvicorn.
CMD ["python", "-m", "app.demo", "300"]
