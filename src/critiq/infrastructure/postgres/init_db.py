from __future__ import annotations

import asyncio
import logging

from critiq.infrastructure.postgres.models import Base
from critiq.infrastructure.postgres.session import engine

logger = logging.getLogger("critiq.initdb")


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema created (metadata.create_all).")


def main() -> None:
    asyncio.run(init_db())


if __name__ == "__main__":
    main()
