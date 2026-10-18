-- Independent local stores; their service owns tables and migrations.
SELECT 'CREATE DATABASE etl_history' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='etl_history')\gexec
SELECT 'CREATE DATABASE etl_stats' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='etl_stats')\gexec
