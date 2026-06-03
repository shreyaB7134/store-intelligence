# Database Migrations

This project uses SQLAlchemy's `init_db()` for automatic table creation on startup.
For production schema migrations, use Alembic:

## Setup Alembic

```bash
pip install alembic
alembic init migrations
```

Configure `alembic.ini` with your DATABASE_URL and run:

```bash
alembic revision --autogenerate -m "Initial schema"
alembic upgrade head
```

## Current Schema

Tables are defined in `app/domain/models.py`:
- `events` — all store events (partitioned by store_id in production)
- `pos_transactions` — POS transaction records
- `visitor_sessions` — aggregated visitor session data

## Indexes

Critical performance indexes:
- `ix_events_store_timestamp` — primary analytics pattern
- `ix_events_store_type` — funnel queries
- `ix_events_visitor_store` — session lookup
- `ix_pos_store_datetime` — POS correlation window queries
