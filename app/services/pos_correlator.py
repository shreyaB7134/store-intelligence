from __future__ import annotations
import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.infrastructure.repositories import POSRepository

logger = logging.getLogger(__name__)


def parse_pos_csv(csv_path: str | Path) -> list[dict]:
    """
    Parse the POS CSV into dicts for DB insertion.
    CSV columns: order_id, order_date, order_time, store_id, product_id, brand_name, total_amount
    """
    records = []
    path = Path(csv_path)
    if not path.exists():
        logger.warning("POS CSV not found: %s", path)
        return records

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                date_str = row["order_date"].strip()
                time_str = row["order_time"].strip()
                # Handle DD-MM-YYYY format
                dt = datetime.strptime(
                    f"{date_str} {time_str}", "%d-%m-%Y %H:%M:%S"
                ).replace(tzinfo=timezone.utc)
                records.append({
                    "order_id": str(row["order_id"]).strip(),
                    "order_datetime": dt,
                    "store_id": str(row["store_id"]).strip(),
                    "product_id": str(row["product_id"]).strip(),
                    "brand_name": str(row["brand_name"]).strip(),
                    "total_amount": float(row["total_amount"]),
                })
            except (ValueError, KeyError) as e:
                logger.warning("Skipping POS row %s: %s", row, e)
    return records


async def load_pos_data(session: AsyncSession, csv_path: str | Path) -> int:
    """Load POS CSV into the database. Returns number of rows inserted."""
    records = parse_pos_csv(csv_path)
    if not records:
        return 0
    repo = POSRepository(session)
    count = await repo.bulk_insert(records)
    logger.info("Loaded %d POS transactions", count)
    return count


async def compute_conversion_rate(
    session: AsyncSession,
    store_id: str,
    unique_visitors: int,
    pos_window_seconds: int = 300,
) -> float:
    """
    Conversion rate = (visitors who visited billing zone AND had a POS transaction
    within pos_window_seconds) / unique_visitors.

    Since we can't match by identity, we use timestamp proximity:
    - Find all billing zone visits
    - For each visit, check if a POS transaction exists within the window
    - Count unique visitors converted this way
    """
    if unique_visitors == 0:
        return 0.0
    from app.infrastructure.repositories import POSRepository, EventRepository
    from app.domain.enums import EventType
    from sqlalchemy import select, distinct
    from app.domain.models import EventRecord
    from datetime import timedelta

    repo = POSRepository(session)

    # Get all billing zone visits
    result = await session.execute(
        select(EventRecord.visitor_id, EventRecord.timestamp).where(
            EventRecord.store_id == store_id,
            EventRecord.event_type.in_([
                EventType.BILLING_QUEUE_JOIN.value,
                EventType.ZONE_ENTER.value,
            ]),
            EventRecord.is_staff == False,
        ).order_by(EventRecord.timestamp)
    )
    billing_visits = result.all()

    converted_visitors: set[str] = set()
    for visitor_id, ts in billing_visits:
        window_start = ts
        window_end = ts + timedelta(seconds=pos_window_seconds)
        transactions = await repo.get_transactions_in_window(
            store_id, window_start, window_end
        )
        if transactions:
            converted_visitors.add(visitor_id)

    return len(converted_visitors) / unique_visitors
