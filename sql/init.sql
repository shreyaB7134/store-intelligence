-- Store Intelligence Platform - PostgreSQL Schema
-- This file is automatically executed by PostgreSQL on first startup.
-- SQLAlchemy will also create tables via init_db() at startup.

-- Ensure the database exists (for idempotency)
-- Tables are created by SQLAlchemy ORM on startup.

-- Create extension for UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Performance: configure for analytics workload
ALTER SYSTEM SET work_mem = '64MB';
ALTER SYSTEM SET max_parallel_workers_per_gather = 2;
SELECT pg_reload_conf();
