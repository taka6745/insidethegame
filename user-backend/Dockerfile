FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements-test.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY migrations ./migrations
COPY fixtures ./fixtures
# Optional live-HLS origin; a fresh named volume inherits this ownership.
RUN mkdir -p /media-live && chown 65532:65532 /media-live
USER 65532:65532
CMD ["uvicorn", "backend.app:from_env", "--factory", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test
USER root
RUN pip install --no-cache-dir -r requirements-test.txt
COPY tests ./tests
COPY benchmarks ./benchmarks
COPY pytest.ini ./
USER 65532:65532
CMD ["pytest", "-q", "-p", "no:cacheprovider"]
