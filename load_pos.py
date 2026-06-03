import asyncio
import os
import sys
from app.infrastructure.database import get_db_session
from app.services.pos_correlator import load_pos_data

async def main():
    csv_path = "../POS - sample transactionsb1e826f.csv"
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found at {csv_path}")
        sys.exit(1)
        
    async with get_db_session() as session:
        count = await load_pos_data(session, csv_path)
        print(f"Successfully loaded {count} POS transactions into the database.")

if __name__ == "__main__":
    asyncio.run(main())
