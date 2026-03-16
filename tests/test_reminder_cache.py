from __future__ import annotations

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from src.services import reminder


class ReminderCacheTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reminder._sent_reminders_fallback.clear()

    async def test_try_reserve_uses_redis_nx(self) -> None:
        redis_client = AsyncMock()
        redis_client.set = AsyncMock(return_value=True)

        with (
            patch("src.services.reminder._get_redis_client", return_value=redis_client),
            patch("src.services.reminder.get_settings", return_value=SimpleNamespace(redis_reminder_ttl_seconds=123)),
        ):
            reserved = await reminder._try_reserve_reminder("user:event")

        self.assertTrue(reserved)
        redis_client.set.assert_awaited_once_with(
            "reminder:sent:user:event",
            "1",
            ex=123,
            nx=True,
        )

    async def test_try_reserve_falls_back_in_memory_when_redis_not_configured(self) -> None:
        with patch("src.services.reminder._get_redis_client", return_value=None):
            first = await reminder._try_reserve_reminder("user:event")
            second = await reminder._try_reserve_reminder("user:event")

        self.assertTrue(first)
        self.assertFalse(second)
