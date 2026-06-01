"""Per-user review notification poller (token-based).

The official 42 API has no webhooks, so to notify a user about peer evaluations
we poll their ``/me/scale_teams`` (as_corrector + as_corrected) with the OAuth
token they explicitly opted into sharing (review-notification consent). Only
devices with ``pref_review`` AND a stored token are polled.

Dedup is namespaced per user and keyed by ``scale_team id + state`` so a slot
booking and its later filled result each notify exactly once. The first poll
after opt-in *seeds* the baseline (records existing scale_teams without pushing)
so enabling the feature doesn't dump a backlog of alerts.
"""
import logging
import time

import httpx

from config import (
    FT_API_BASE,
    FT_API_CLIENT_ID,
    FT_API_CLIENT_SECRET,
    FT_TOKEN_URL,
)
from pollers.base import BasePoller

logger = logging.getLogger(__name__)


class ReviewPoller(BasePoller):
    name = "review_poller"
    interval_seconds = 300

    def __init__(self, device_repo, notification_repo, state_repo, push):
        self._devices = device_repo
        self._notifications = notification_repo
        self._state = state_repo
        self._push = push

    # poll/diff/notify are unused — run() drives a per-device token loop.
    async def poll(self) -> list[dict]:
        return []

    async def diff(self, new_items: list[dict]) -> list[dict]:
        return []

    async def notify(self, changes: list[dict]) -> None:
        return None

    async def _refresh_token(self, device) -> str | None:
        """Exchange the stored refresh_token for a new access token and persist
        it. Returns the new access token, or None if the grant was revoked."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(FT_TOKEN_URL, data={
                "grant_type": "refresh_token",
                "client_id": FT_API_CLIENT_ID,
                "client_secret": FT_API_CLIENT_SECRET,
                "refresh_token": device["refresh_token"],
            })
        if resp.status_code != 200:
            logger.warning("ReviewPoller: refresh failed for %s (%d)",
                           device.get("login"), resp.status_code)
            return None
        data = resp.json()
        access = data["access_token"]
        expires_at = time.time() + int(data.get("expires_in", 7200))
        await self._devices.update_token(
            device["fcm_token"], access, expires_at,
            refresh_token=data.get("refresh_token"),
        )
        return access

    async def _fetch(self, access_token, path) -> list | None:
        """GET a scale_teams endpoint. None signals 401 (token needs refresh)."""
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{FT_API_BASE}/me/scale_teams/{path}",
                params={"page[size]": 100, "sort": "-updated_at"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if resp.status_code == 401:
            return None
        if resp.status_code != 200:
            logger.error("ReviewPoller: %s -> %d", path, resp.status_code)
            return []
        return resp.json()

    @staticmethod
    def _counterpart(team, as_corrector) -> str:
        if as_corrector:
            cs = team.get("correcteds") or []
            if cs and isinstance(cs[0], dict):
                return cs[0].get("login", "?")
            return "?"
        c = team.get("corrector")
        return c.get("login", "?") if isinstance(c, dict) else "?"

    async def _run_for_device(self, device) -> None:
        user_id = device["user_id"]
        login = device.get("login")
        access = device.get("access_token")
        seeded = device.get("review_seeded", False)
        logger.debug("ReviewPoller: device login=%s seeded=%s", login, seeded)

        teams = None
        for _ in range(2):
            corrector = await self._fetch(access, "as_corrector")
            corrected = await self._fetch(access, "as_corrected")
            if corrector is None or corrected is None:
                logger.info("ReviewPoller: 401 for %s, refreshing token", login)
                access = await self._refresh_token(device)
                if not access:
                    logger.warning("ReviewPoller: token revoked for %s, clearing",
                                   login)
                    await self._devices.clear_token(device["fcm_token"])
                    return
                continue
            teams = ([(t, True) for t in corrector]
                     + [(t, False) for t in corrected])
            break
        if teams is None:
            return
        logger.debug("ReviewPoller: %s has %d scale_team(s)", login, len(teams))

        for team, as_corrector in teams:
            tid = team.get("id")
            state = "filled" if team.get("filled_at") else "scheduled"
            sig = f"{user_id}:scaleteam:{tid}:{state}"
            project = (team.get("team") or {}).get("name") or "project"
            other = self._counterpart(team, as_corrector)
            if state == "filled":
                title = "Evaluation result"
                body = f"{project} · {other} · mark {team.get('final_mark')}"
            else:
                title = "Evaluation scheduled"
                role = "you correct" if as_corrector else "corrected by"
                body = f"{project} · {role} {other} · {team.get('begin_at')}"

            is_new = await self._notifications.insert(
                signature=sig, title=title, body=body,
                source_date=team.get("begin_at"))
            if not is_new:
                continue
            # Baseline run: record existing items but don't push a backlog.
            if not seeded:
                continue
            logger.info("ReviewPoller: push '%s' to %s", title, login)
            await self._push.send(
                tokens=[device["fcm_token"]],
                title=title, body=body,
                data={"type": "review", "scale_team_id": str(tid)})

        if not seeded:
            await self._devices.mark_review_seeded(device["fcm_token"])

    async def run(self) -> None:
        logger.info("ReviewPoller: run start")
        try:
            devices = await self._devices.get_with_token()
            logger.info("ReviewPoller: polling %d opted-in device(s)", len(devices))
            for d in devices:
                try:
                    await self._run_for_device(d)
                except Exception:
                    logger.exception("ReviewPoller: error for user %s",
                                     d.get("login"))
            await self._state.update(self.name, success=True)
            logger.info("ReviewPoller: run done")
        except Exception:
            logger.exception("ReviewPoller run error")
            await self._state.update(self.name, success=False)
