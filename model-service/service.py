"""model-service entrypoint (v8, ADR 0043).

The sidecar's FastAPI app lives in the engine package (`app.model_service`) so it
loads the being's learned models through the SAME `app.ml` code the engine uses
and is covered by the engine test suite. This thin module is the container's
import target:

    uvicorn service:app --host 0.0.0.0 --port 8500
"""
from app.model_service import app, create_app  # noqa: F401  (re-exported for the container)
