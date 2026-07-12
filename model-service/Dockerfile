# model-service sidecar (v8, ADR 0043): serves the being's learned models (outcome
# + instinct) OUT-OF-PROCESS over HTTP so torch never bloats the engine runtime.
# Build from the REPO ROOT (context: .) so it can copy the engine `app` package
# the FastAPI app loads models through:
#   docker compose --profile models up model-service     (or: build model-service)
FROM python:3.12-slim
WORKDIR /srv

# Engine runtime deps (config load, FastAPI) + serving-only deps (torch/numpy).
COPY engine/requirements.txt /tmp/engine-requirements.txt
COPY model-service/requirements.txt /tmp/service-requirements.txt
RUN pip install --no-cache-dir -r /tmp/engine-requirements.txt -r /tmp/service-requirements.txt

# The engine app package (app.ml.*, app.config_service, app.model_service) and the
# thin entrypoint. Config + model artifacts are mounted at runtime (see compose).
COPY engine/app /srv/app
COPY model-service/service.py /srv/service.py
ENV PYTHONPATH=/srv

EXPOSE 8500
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8500"]
