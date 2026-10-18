FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt requirements-test.txt ./
RUN pip install --no-cache-dir -r requirements-test.txt
COPY demo_etl ./demo_etl
COPY tests ./tests
RUN useradd --create-home app
USER app
EXPOSE 8000
CMD ["uvicorn", "demo_etl.app:from_env", "--factory", "--host", "0.0.0.0", "--port", "8000"]
