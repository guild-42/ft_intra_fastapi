import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


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
        logger.info("%s: run start", self.name)
        items = await self.poll()
        logger.info("%s: polled %d item(s)", self.name, len(items))
        changes = await self.diff(items)
        logger.info("%s: %d change(s) after diff", self.name, len(changes))
        if changes:
            await self.notify(changes)
        logger.info("%s: run done", self.name)
