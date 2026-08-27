from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.events.kafka_events import relay


async def main() -> None:
    while True:
        result = await relay.relay_once()
        if result["published"] or result["failed"]:
            print(json.dumps(result, sort_keys=True))
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
