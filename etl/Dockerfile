# Local Stream Analytics stand-in (local_stream/): Event Hubs → reference rules → SQL Server + Service Bus.
# Used by the shared local Docker stack; Azure runs the Stream Analytics job instead and this image only as
# the purge API (ETL_ROLE=admin, infra/admin.tf) and the SPADL post-processor (ETL_ROLE=spadl, infra/spadl.tf).
FROM python:3.12-slim AS stream
WORKDIR /app
# mssql-python's bundled driver needs these (Azure SQL with managed identity).
RUN apt-get update && apt-get install -y --no-install-recommends libltdl7 libkrb5-3 libgssapi-krb5-2 \
    && rm -rf /var/lib/apt/lists/*
COPY local_stream/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY contracts ./contracts
COPY reference ./reference
COPY local_stream ./local_stream
COPY spadl ./spadl
RUN useradd --create-home app
USER app
CMD ["python", "-m", "local_stream"]
