# The recorded-match stand-in (demo_etl/) used by the local Docker stack; see docs/components/demo-etl.md.
FROM python:3.12-slim AS base
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY demo_etl ./demo_etl
RUN useradd --create-home app
USER app
EXPOSE 8000
CMD ["uvicorn", "demo_etl.app:from_env", "--factory", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS test
USER root
COPY requirements-test.txt ./
RUN pip install --no-cache-dir -r requirements-test.txt
COPY tests ./tests
USER app
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]

# A plain docker build produces the service, never the test runner.
FROM base AS runtime
