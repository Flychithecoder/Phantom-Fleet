"""Tests for the hybrid foreground+API concurrency runner."""
import asyncio
import pytest

from phantom_fleet.core.hybrid_runner import (
    ExecutionMode,
    execution_mode,
    BACKGROUND_API_PLATFORMS,
    FOREGROUND_ONLY_PLATFORMS,
    DeviceProfile,
    PlatformHeaders,
    PhoneSlotLock,
    WorkerTask,
    WorkerResult,
    BackgroundWorker,
    InstagramAPIWorker,
    PhoneHybridRunner,
    WORKER_CLASSES,
    build_fleet_runners,
)


# ---------------------------------------------------------------------------
# Platform mode classification
# ---------------------------------------------------------------------------


def test_api_platforms_classified_correctly():
    for p in ("instagram", "threads", "x", "reddit", "telegram", "discord", "bluesky"):
        assert execution_mode(p) == ExecutionMode.BACKGROUND_API, f"{p} should be BACKGROUND_API"
    # LinkedIn excluded from OFM build — would be BACKGROUND_API in general brand


def test_foreground_platforms_classified_correctly():
    for p in ("tiktok", "tinder", "bumble", "hinge", "grindr"):
        assert execution_mode(p) == ExecutionMode.FOREGROUND_UI, f"{p} should be FOREGROUND_UI"


def test_no_platform_in_both_sets():
    overlap = BACKGROUND_API_PLATFORMS & FOREGROUND_ONLY_PLATFORMS
    assert len(overlap) == 0, f"Platform in both sets: {overlap}"


# ---------------------------------------------------------------------------
# DeviceProfile helpers
# ---------------------------------------------------------------------------


def make_headers(platform: str, phone_serial: str) -> PlatformHeaders:
    return PlatformHeaders(
        platform=platform,
        session_token=f"tok_{platform}_{phone_serial}",
        device_id=f"dev_{platform}_{phone_serial}",
        user_agent=f"Mozilla/5.0 ({platform})",
        app_version="1.0.0",
        android_id="abc123def456",
        advertising_id="gaid-0000-1111",
        carrier_name="T-Mobile",
        carrier_mcc_mnc="310260",
        locale="en_US",
        timezone="America/New_York",
    )


def make_device_profile(
    phone_serial: str,
    platforms: list[str],
) -> DeviceProfile:
    headers = {p: make_headers(p, phone_serial) for p in platforms}
    return DeviceProfile(
        phone_serial=phone_serial,
        model="Samsung Galaxy S10 Lite",
        android_version="12",
        android_id="abc123def456",
        advertising_id="gaid-0000-1111",
        carrier_name="T-Mobile",
        carrier_mcc_mnc="310260",
        timezone="America/New_York",
        locale="en_US",
        platform_headers=headers,
    )


def test_device_profile_supported_api_platforms():
    profile = make_device_profile("PHONE_001", ["instagram", "threads", "tiktok", "telegram"])
    api = set(profile.supported_api_platforms())
    # tiktok is FOREGROUND_ONLY so it should not appear in supported_api_platforms
    assert "instagram" in api
    assert "threads" in api
    assert "telegram" in api
    assert "tiktok" not in api


def test_device_profile_headers_for():
    profile = make_device_profile("PHONE_002", ["instagram", "reddit"])
    ig_headers = profile.headers_for("instagram")
    assert ig_headers is not None
    assert ig_headers.platform == "instagram"
    assert profile.headers_for("tiktok") is None


# ---------------------------------------------------------------------------
# PhoneSlotLock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_foreground_lock_exclusive():
    lock = PhoneSlotLock("PHONE_003")
    acquired1 = await lock.acquire_foreground("instagram")
    assert acquired1
    assert lock.foreground_platform == "instagram"

    # Second acquire should timeout (exclusive lock held)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(lock._foreground_lock.acquire(), timeout=0.05)
    lock.release_foreground()
    assert lock.foreground_platform is None


@pytest.mark.asyncio
async def test_account_lock_concurrent():
    lock = PhoneSlotLock("PHONE_004")
    # Two different accounts can be locked concurrently
    a1 = await lock.acquire_account("acc_001")
    a2 = await lock.acquire_account("acc_002")
    assert a1 and a2
    lock.release_account("acc_001")
    lock.release_account("acc_002")


@pytest.mark.asyncio
async def test_account_lock_same_account_blocks():
    lock = PhoneSlotLock("PHONE_005")
    acquired = await lock.acquire_account("acc_shared")
    assert acquired

    # Same account second acquire should timeout
    result = await lock.acquire_account("acc_shared")
    assert not result  # times out → returns False
    lock.release_account("acc_shared")


# ---------------------------------------------------------------------------
# BackgroundWorker base
# ---------------------------------------------------------------------------


class DummyWorker(BackgroundWorker):
    PLATFORM = "instagram"

    def __init__(self, *args, succeed=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.succeed = succeed
        self.executed: list[str] = []

    async def execute_task(self, task: WorkerTask) -> WorkerResult:
        self.executed.append(task.task_id)
        if not self.succeed:
            raise RuntimeError("simulated API error")
        return WorkerResult(
            task_id=task.task_id,
            platform=self.PLATFORM,
            account_id=task.account_id,
            success=True,
            data={"action": task.action},
        )

    @staticmethod
    async def _human_sleep(*args, **kwargs):
        pass  # skip sleep in tests


def make_worker(phone_serial="PHONE_W01", succeed=True) -> DummyWorker:
    profile = make_device_profile(phone_serial, ["instagram"])
    lock = PhoneSlotLock(phone_serial)
    return DummyWorker(
        phone_serial=phone_serial,
        device_profile=profile,
        slot_lock=lock,
        succeed=succeed,
    )


def make_task(task_id: str, account_id: str = "acc_001") -> WorkerTask:
    return WorkerTask(
        task_id=task_id,
        platform="instagram",
        account_id=account_id,
        phone_serial="PHONE_W01",
        action="follow",
        params={"target_id": "target_123"},
    )


@pytest.mark.asyncio
async def test_worker_processes_tasks():
    worker = make_worker()
    worker.enqueue(make_task("t1", "acc_001"))
    worker.enqueue(make_task("t2", "acc_002"))
    await worker.run(max_tasks=10)
    results = await worker.drain_results()
    assert len(results) == 2
    assert all(r.success for r in results)


@pytest.mark.asyncio
async def test_worker_handles_api_error():
    worker = make_worker(succeed=False)
    worker.enqueue(make_task("t3"))
    await worker.run(max_tasks=1)
    results = await worker.drain_results()
    assert len(results) == 1
    assert not results[0].success
    assert "simulated API error" in results[0].error


@pytest.mark.asyncio
async def test_worker_no_headers_fails_gracefully():
    # Device profile with no IG headers
    profile = make_device_profile("PHONE_W02", ["telegram"])
    lock = PhoneSlotLock("PHONE_W02")
    worker = DummyWorker(
        phone_serial="PHONE_W02",
        device_profile=profile,
        slot_lock=lock,
    )
    # IG headers are None — should get no_device_headers_extracted
    task = WorkerTask(
        task_id="t_no_hdr",
        platform="instagram",
        account_id="acc_nohdr",
        phone_serial="PHONE_W02",
        action="follow",
    )
    worker.enqueue(task)
    await worker.run(max_tasks=1)
    results = await worker.drain_results()
    assert len(results) == 1
    assert not results[0].success
    assert results[0].error == "no_device_headers_extracted"


# ---------------------------------------------------------------------------
# PhoneHybridRunner
# ---------------------------------------------------------------------------


def make_runner(phone_serial="PHONE_R01") -> PhoneHybridRunner:
    profile = make_device_profile(
        phone_serial,
        list(BACKGROUND_API_PLATFORMS),  # all 8 API platforms
    )
    return PhoneHybridRunner(profile)


def test_runner_initializes_workers_for_api_platforms():
    runner = make_runner()
    for platform in BACKGROUND_API_PLATFORMS:
        worker = runner.worker_for(platform)
        assert worker is not None, f"Expected worker for {platform}"


def test_runner_no_worker_for_foreground_only():
    runner = make_runner()
    for platform in FOREGROUND_ONLY_PLATFORMS:
        assert runner.worker_for(platform) is None


def test_runner_enqueue_api_task():
    runner = make_runner("PHONE_R02")
    task = WorkerTask(
        task_id="qt1",
        platform="instagram",
        account_id="acc_enqueue",
        phone_serial="PHONE_R02",
        action="follow",
    )
    assert runner.enqueue_api_task(task) is True


def test_runner_enqueue_foreground_task_returns_false():
    runner = make_runner("PHONE_R03")
    task = WorkerTask(
        task_id="qt2",
        platform="tiktok",
        account_id="acc_tiktok",
        phone_serial="PHONE_R03",
        action="scroll",
    )
    assert runner.enqueue_api_task(task) is False


def test_runner_throughput_summary():
    runner = make_runner("PHONE_R04")
    summary = runner.throughput_summary()
    assert summary["phone_serial"] == "PHONE_R04"
    assert "api_workers" in summary
    assert "queue_depths" in summary
    assert set(summary["api_workers"]) == BACKGROUND_API_PLATFORMS


# ---------------------------------------------------------------------------
# Fleet builder
# ---------------------------------------------------------------------------


def test_build_fleet_runners():
    profiles = [
        make_device_profile(f"PHONE_{i:03d}", list(BACKGROUND_API_PLATFORMS))
        for i in range(5)
    ]
    fleet = build_fleet_runners(profiles)
    assert len(fleet) == 5
    for serial, runner in fleet.items():
        assert runner.phone_serial == serial
        assert len(runner._workers) == len(BACKGROUND_API_PLATFORMS)


# ---------------------------------------------------------------------------
# Worker registry completeness
# ---------------------------------------------------------------------------


def test_all_api_platforms_have_worker_class():
    for platform in BACKGROUND_API_PLATFORMS:
        assert platform in WORKER_CLASSES, (
            f"Platform {platform} in BACKGROUND_API_PLATFORMS but no entry in WORKER_CLASSES"
        )
