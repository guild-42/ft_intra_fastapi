from abc import ABC, abstractmethod


class BasePoller(ABC):
    name: str
    interval_seconds: int

    @abstractmethod
    async def poll(self) -> list[dict]:
        ...

    @abstractmethod
    async def diff(self, new_items: list[dict]) -> list[dict]:
        ...

    @abstractmethod
    async def notify(self, changes: list[dict]) -> None:
        ...

    async def run(self) -> None:
        items = await self.poll()
        changes = await self.diff(items)
        if changes:
            await self.notify(changes)
