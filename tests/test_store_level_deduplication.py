import pytest
from datetime import datetime, timezone, timedelta
from app.domain.enums import EventType
from app.domain.models import VisitorSession
from app.infrastructure.repositories import EventRepository
from tests.conftest import make_event

@pytest.mark.asyncio
async def test_store_level_deduplication(db_session):
    repo = EventRepository(db_session)
    store_id = "ST_TEST"
    visitor_id = "V_100"
    
    t1 = datetime.now(timezone.utc)
    ev1 = make_event(
        event_type=EventType.ENTRY,
        visitor_id=visitor_id,
        store_id=store_id,
        camera_id="CAM_ENTRY",
        timestamp=t1
    )
    await repo.upsert(ev1)
    
    # Occupancy should be 1
    occ1 = await repo.get_current_occupancy(store_id)
    assert occ1 == 1, "Occupancy should be 1 after entry"
    
    # Second camera entry (double count scenario)
    t2 = t1 + timedelta(seconds=10)
    ev2 = make_event(
        event_type=EventType.ENTRY,
        visitor_id=visitor_id,
        store_id=store_id,
        camera_id="CAM_2",
        timestamp=t2
    )
    await repo.upsert(ev2)
    
    # Occupancy should STILL be 1
    occ2 = await repo.get_current_occupancy(store_id)
    assert occ2 == 1, "Occupancy should still be 1 after second camera entry"
    
    # Unique visitors should be 1
    unique_visitors = await repo.get_unique_visitor_count(store_id)
    assert unique_visitors == 1, "Unique visitors should be 1"

    # Internal zone transition (not an exit)
    t3 = t2 + timedelta(seconds=30)
    ev3 = make_event(
        event_type=EventType.ZONE_ENTER,
        visitor_id=visitor_id,
        store_id=store_id,
        camera_id="CAM_2",
        zone_id="ZONE_A",
        timestamp=t3
    )
    await repo.upsert(ev3)
    occ3 = await repo.get_current_occupancy(store_id)
    assert occ3 == 1, "Occupancy should still be 1 after internal zone enter"

    # Timeout logic test
    from sqlalchemy import update
    await db_session.execute(
        update(VisitorSession)
        .where(VisitorSession.visitor_id == visitor_id)
        .values(last_seen_at=t3 - timedelta(hours=2))
    )
    # Don't commit, we are in an active transaction, but the execute applies to this session
    
    occ_timeout = await repo.get_current_occupancy(store_id)
    assert occ_timeout == 0, "Occupancy should be 0 due to 30 min timeout"

    # Bring them back to test explicit exit
    await db_session.execute(
        update(VisitorSession)
        .where(VisitorSession.visitor_id == visitor_id)
        .values(last_seen_at=t3)
    )

    # 4. Exit Event
    t4 = t3 + timedelta(minutes=5)
    ev4 = make_event(
        event_type=EventType.EXIT,
        visitor_id=visitor_id,
        store_id=store_id,
        camera_id="CAM_ENTRY",
        timestamp=t4
    )
    await repo.upsert(ev4)
    
    # Now it's explicitly exited
    occ_exit = await repo.get_current_occupancy(store_id)
    assert occ_exit == 0, "Occupancy should be 0 after explicit exit"
    
    # 5. Re-entry Event
    t5 = t4 + timedelta(minutes=10)
    ev5 = make_event(
        event_type=EventType.ENTRY,
        visitor_id=visitor_id,
        store_id=store_id,
        camera_id="CAM_ENTRY",
        timestamp=t5
    )
    await repo.upsert(ev5)
    
    # Session should be reactivated
    occ_reentry = await repo.get_current_occupancy(store_id)
    assert occ_reentry == 1, "Occupancy should be 1 after reentry (session reactivated)"
