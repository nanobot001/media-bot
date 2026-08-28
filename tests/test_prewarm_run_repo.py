import asyncio
import datetime as dt
from unittest.mock import AsyncMock, patch

import pytest

from moviebot.config import settings
from moviebot.core.background_prewarmer import (
    run_cache_prewarm_cycle,
    start_background_prewarm_loop,
)
from moviebot.db.connection import init_db
from moviebot.db.prewarm_run_repo import PrewarmRunRepository


UTC = dt.timezone.utc


@pytest.fixture(autouse=True)
def isolated_prewarm_ledger(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "prewarm-ledger.sqlite3"))
    monkeypatch.setattr(settings, "tv_database_path", str(tmp_path / "tv.sqlite3"))
    monkeypatch.setattr(settings, "tv_classic_database_path", str(tmp_path / "tv-classic.sqlite3"))
    init_db("movies")
    init_db("tv")
    init_db("tv_classic")


def _acquire(now: dt.datetime, runtime_id: str = "runtime-a", lease_seconds: int = 300):
    return PrewarmRunRepository.acquire(
        trigger_source="manual",
        runtime_id=runtime_id,
        process_id=1234,
        interval_hours=6,
        lease_seconds=lease_seconds,
        now=now,
    )


def test_completed_cycle_persists_counts_and_next_due():
    started = dt.datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    PrewarmRunRepository.set_next_due(started)
    reservation = _acquire(started)
    assert reservation["accepted"] is True
    assert PrewarmRunRepository.get_runtime_state()["next_due_at"] is None

    assert PrewarmRunRepository.heartbeat(
        reservation["cycle_id"],
        "runtime-a",
        lease_seconds=300,
        now=started + dt.timedelta(minutes=1),
    ) is True

    finished = started + dt.timedelta(minutes=2)
    row = PrewarmRunRepository.finish(
        reservation["cycle_id"],
        "runtime-a",
        status="completed",
        interval_hours=6,
        stats={
            "reverified_count": 49,
            "cached_count": 7,
            "cloud_cached_count": 11,
            "provider_error_count": 2,
        },
        stop_reason="completed",
        now=finished,
    )

    assert row["status"] == "completed"
    assert row["phase_counts"]["reverified_count"] == 49
    assert row["provider_error_count"] == 2
    assert row["next_due_at"] == "2026-08-28T18:02:00Z"
    status = PrewarmRunRepository.status(limit=10)
    assert status["is_prewarming"] is False
    assert status["last_cycle"]["cycle_id"] == reservation["cycle_id"]
    assert status["next_due_at"] == "2026-08-28T18:02:00Z"
    assert "runtime_id" not in status["last_cycle"]
    assert "process_id" not in status["last_cycle"]


def test_concurrent_attempt_is_recorded_as_skipped_busy():
    started = dt.datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    active = _acquire(started)
    rejected = _acquire(started + dt.timedelta(seconds=1), runtime_id="runtime-b")

    assert active["accepted"] is True
    assert rejected == {
        "accepted": False,
        "cycle_id": rejected["cycle_id"],
        "status": "skipped",
        "error_code": "PREWARM_BUSY",
        "active_cycle_id": active["cycle_id"],
    }
    rejected_row = PrewarmRunRepository.get(rejected["cycle_id"])
    assert rejected_row["status"] == "skipped"
    assert rejected_row["stop_reason"] == "busy"
    assert PrewarmRunRepository.status()["active_cycle"]["cycle_id"] == active["cycle_id"]


def test_expired_lease_is_interrupted_before_new_acquisition():
    started = dt.datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    first = _acquire(started, lease_seconds=300)
    recovered_at = started + dt.timedelta(seconds=301)

    stale_ids = PrewarmRunRepository.reconcile_stale(now=recovered_at)
    assert stale_ids == [first["cycle_id"]]
    interrupted = PrewarmRunRepository.get(first["cycle_id"])
    assert interrupted["status"] == "interrupted"
    assert interrupted["stop_reason"] == "lease_expired"

    replacement = _acquire(recovered_at, runtime_id="runtime-b")
    assert replacement["accepted"] is True


def test_history_is_retained_and_available_in_bounded_pages():
    started = dt.datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    active = _acquire(started)
    for offset in range(11):
        _acquire(started + dt.timedelta(seconds=offset + 1), runtime_id=f"runtime-{offset}")

    first_page = PrewarmRunRepository.status(limit=10, offset=0)
    second_page = PrewarmRunRepository.status(limit=10, offset=10)
    assert first_page["cycle_history_total"] == 12
    assert len(first_page["recent_cycles"]) == 10
    assert len(second_page["recent_cycles"]) == 2
    assert first_page["active_cycle"]["cycle_id"] == active["cycle_id"]


def test_failure_text_is_sanitized_before_public_status():
    started = dt.datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    reservation = _acquire(started)
    PrewarmRunRepository.finish(
        reservation["cycle_id"],
        "runtime-a",
        status="failed",
        interval_hours=6,
        stats={},
        error_code="PROVIDER_FAILURE",
        error_message=r"Failed https://provider.invalid/token=secret at C:\private\media\file.mkv magnet:?xt=urn:btih:secret",
        now=started + dt.timedelta(minutes=1),
    )

    public_row = PrewarmRunRepository.status()["last_cycle"]
    assert "provider.invalid" not in public_row["error_message"]
    assert "C:\\private" not in public_row["error_message"]
    assert "btih:secret" not in public_row["error_message"]
    assert "[redacted-url]" in public_row["error_message"]
    assert "[redacted-path]" in public_row["error_message"]
    assert "[redacted-magnet]" in public_row["error_message"]


@pytest.mark.asyncio
async def test_restart_loop_preserves_future_due_without_immediate_rerun():
    started = dt.datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
    reservation = _acquire(started)
    PrewarmRunRepository.finish(
        reservation["cycle_id"],
        "runtime-a",
        status="completed",
        interval_hours=6,
        stats={},
        now=started + dt.timedelta(minutes=1),
    )

    with patch(
        "moviebot.core.background_prewarmer.run_cache_prewarm_cycle",
        new_callable=AsyncMock,
    ) as run_cycle:
        task = asyncio.create_task(
            start_background_prewarm_loop(startup_delay_seconds=0, poll_seconds=0.01)
        )
        await asyncio.sleep(0.04)
        task.cancel()
        await task

    run_cycle.assert_not_awaited()
    assert PrewarmRunRepository.get_runtime_state()["next_due_at"] == "2030-01-01T18:01:00Z"


@pytest.mark.asyncio
async def test_cycle_runner_completes_reserved_ledger_row():
    from moviebot.db.connection import get_db_connection

    fake_provider = type("FakeProvider", (), {"get_trending_tv": lambda self, page=1: {"results": []}})
    with patch(
        "moviebot.core.background_prewarmer.batch_reverify_existing",
        new=AsyncMock(return_value={"verified": 3, "dropped": 0, "provider_errors": 0}),
    ), patch(
        "moviebot.core.background_prewarmer.get_progressive_frontier_candidates",
        return_value=[],
    ), patch(
        "moviebot.core.background_prewarmer.get_recent_movie_frontier_candidates",
        return_value=[],
    ), patch(
        "moviebot.core.background_prewarmer.get_all_time_popular_movie_frontier_candidates",
        return_value=[],
    ), patch(
        "moviebot.core.background_prewarmer.TMDbFactProvider",
        fake_provider,
    ), patch(
        "moviebot.core.background_prewarmer.CachePrewarmRepository.get_scoreboard_stats",
        return_value={"instant_cached": 0},
    ):
        result = await run_cache_prewarm_cycle(trigger_source="manual", interval_hours=6)

    assert result["ok"] is True
    row = PrewarmRunRepository.get(result["cycle_id"])
    assert row["status"] == "completed"
    assert row["phase_counts"]["reverified_count"] == 3
    with get_db_connection("movies") as conn:
        transfer_count = conn.execute("SELECT COUNT(*) FROM cloud_transfer_intents").fetchone()[0]
    assert transfer_count == 0


@pytest.mark.asyncio
async def test_web_startup_starts_scheduler_even_when_plex_sync_fails():
    from moviebot.api.webhook import on_startup_sync_plex

    fake_client = type(
        "FakePlexClient",
        (),
        {"fetch_all_movies": AsyncMock(side_effect=RuntimeError("Plex unavailable"))},
    )()
    with patch(
        "moviebot.core.background_prewarmer.start_background_prewarm_scheduler"
    ) as start_scheduler, patch(
        "moviebot.adapters.plex_client.PlexClient",
        return_value=fake_client,
    ), patch(
        "moviebot.api.webhook.EventRepository.insert"
    ) as record_event:
        await on_startup_sync_plex()
        await asyncio.sleep(0.02)

    start_scheduler.assert_called_once_with()
    record_event.assert_called_once()
    assert record_event.call_args.kwargs["event_type"] == "plex_startup_sync_failed"
