from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.events.kafka_consumer import KafkaEventConsumer


async def main() -> None:
    stats = await KafkaEventConsumer().run()
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
