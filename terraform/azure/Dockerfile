# Toolbox for `./dev azure`: pinned Terraform (as `./dev terraform check`), Azure CLI, go-sqlcmd
# (ETL azure-setup) and azcopy (media upload, many files in parallel). Uses the developer's `az login` through a mounted ~/.azure; no other credentials.
FROM hashicorp/terraform:1.13.4 AS terraform

FROM mcr.microsoft.com/azure-cli:2.91.0
ARG TARGETARCH
ARG SQLCMD_VERSION=1.10.0
RUN tdnf install -y bzip2 tar azcopy && tdnf clean all \
 && curl -fsSL "https://github.com/microsoft/go-sqlcmd/releases/download/v${SQLCMD_VERSION}/sqlcmd-linux-${TARGETARCH}.tar.bz2" \
    | tar -xj -C /usr/local/bin sqlcmd \
 && sqlcmd --version
COPY --from=terraform /bin/terraform /usr/local/bin/terraform
ENV TF_IN_AUTOMATION=1 TF_INPUT=0 AZURE_CORE_COLLECT_TELEMETRY=no AZURE_CORE_ONLY_SHOW_ERRORS=yes
