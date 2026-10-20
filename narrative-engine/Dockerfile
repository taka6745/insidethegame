FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY narrative_demo ./narrative_demo
COPY fixtures ./fixtures
RUN mkdir /data && useradd --uid 10001 --no-create-home app && chown app /data
USER app
ENV NARRATIVE_DATABASE_PATH=/data/narrative.sqlite3
EXPOSE 8000
CMD ["uvicorn", "narrative_demo.app:from_env", "--factory", "--host", "0.0.0.0", "--port", "8000"]
