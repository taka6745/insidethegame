# The engine service. Build with `python -m narrative_engine.devtools.azure build`, which sends only
# narrative_engine/, requirements.txt and this file to ACR (never .env or the LLM setup notes).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY narrative_engine narrative_engine
RUN useradd --uid 10001 engine
USER engine

EXPOSE 8000
CMD ["python", "-m", "narrative_engine.service"]
