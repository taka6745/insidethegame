#!/usr/bin/env bash
# Create the ETL database and apply sql/migrations, then the local worker's state tables,
# recording each file in dbo.schemaMigrations (as devtools migrate does). Safe to rerun.
set -euo pipefail
sql() { /opt/mssql-tools18/bin/sqlcmd -S "${SQL_HOST:-sql}" -U sa -C -b -I "$@"; }
db="${ETL_SQL_DATABASE:-insidethegame}"
sql -d master -Q "IF DB_ID('$db') IS NULL CREATE DATABASE [$db]"
sql -d "$db" -Q "IF OBJECT_ID('dbo.schemaMigrations') IS NULL CREATE TABLE dbo.schemaMigrations (name nvarchar(200) PRIMARY KEY, appliedAt datetime2(3) NOT NULL DEFAULT sysutcdatetime())"
for file in /migrations/*.sql /local/*.sql; do
  name="${file#/}"; name="${name/migrations\//}"
  applied=$(sql -d "$db" -h -1 -W -Q "SET NOCOUNT ON; SELECT COUNT(*) FROM dbo.schemaMigrations WHERE name = '$name'")
  if [[ "$(echo "$applied" | tr -d '[:space:]')" == 0 ]]; then
    sql -d "$db" -x -i "$file"
    sql -d "$db" -Q "INSERT dbo.schemaMigrations (name) VALUES ('$name')"
    echo "applied $name"
  fi
done
echo "migrations up to date"
