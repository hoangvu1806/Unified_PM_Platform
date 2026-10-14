import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from uuid import UUID

from ..models import WorkflowEvent
from ..storage.store import Store


class EventStream:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.listeners: dict[UUID, set[asyncio.Queue[WorkflowEvent]]] = defaultdict(set)

    async def publish(self, event: WorkflowEvent) -> None:
        for queue in tuple(self.listeners[event.run_id]):
            queue.put_nowait(event)

    async def emit(self, run_id: UUID, revision: int, event_type: str, payload: dict[str, object]) -> WorkflowEvent:
        event = await self.store.add_event(run_id, revision, event_type, payload)
        await self.publish(event)
        return event

    async def subscribe(self, run_id: UUID, after: int = 0) -> AsyncIterator[str]:
        for event in await self.store.list_events(run_id, after):
            yield self.encode(event)
            after = event.sequence
        queue: asyncio.Queue[WorkflowEvent] = asyncio.Queue()
        self.listeners[run_id].add(queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield self.encode(event)
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            self.listeners[run_id].discard(queue)

    @staticmethod
    def encode(event: WorkflowEvent) -> str:
        data = event.model_dump(mode="json", by_alias=True)
        return f"id: {event.sequence}\nevent: {event.type}\ndata: {json.dumps(data)}\n\n"
