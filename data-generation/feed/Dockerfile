# Simulated external match-data and broadcast provider. Build context: data-generation/.
# Recordings and media are mounted at runtime, never baked into the image.
FROM python:3.12-slim AS base
WORKDIR /app
COPY feed/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY grf_demo ./grf_demo
COPY feed ./feed
RUN useradd --create-home app && mkdir -p /live-media && chown app /live-media
USER app
EXPOSE 8000
CMD ["uvicorn", "feed.app:from_env", "--factory", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS test
USER root
RUN pip install --no-cache-dir -r feed/requirements-test.txt
COPY recordings ./recordings
USER app
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "feed"]

# A plain docker build produces the service, never the test runner.
FROM base AS runtime
