from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.events.kafka_events import relay


async def run(event_id: str) -> None:
    print(json.dumps(await relay.replay_event(event_id), ensure_ascii=False, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.event_id))


if __name__ == "__main__":
    main()
