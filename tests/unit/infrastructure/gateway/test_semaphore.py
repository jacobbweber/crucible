"""Unit tests for InferenceSemaphore concurrency management."""

import asyncio

import pytest

from agent_os.infrastructure.gateway.semaphore import InferenceSemaphore


@pytest.mark.asyncio
async def test_semaphore_concurrency_limiting() -> None:
    """Verify max_concurrency=1 forces serial execution for two concurrent tasks."""
    semaphore = InferenceSemaphore(max_concurrency=1)
    max_observed_concurrency = 0
    execution_order: list[str] = []

    async def worker(task_name: str) -> None:
        nonlocal max_observed_concurrency
        async with semaphore.acquire():
            max_observed_concurrency = max(max_observed_concurrency, semaphore.active_workers)
            execution_order.append(f"{task_name}_start")
            await asyncio.sleep(0.05)
            execution_order.append(f"{task_name}_end")

    await asyncio.gather(worker("task_1"), worker("task_2"))

    assert max_observed_concurrency == 1
    # Verify serial execution order
    assert execution_order in (
        ["task_1_start", "task_1_end", "task_2_start", "task_2_end"],
        ["task_2_start", "task_2_end", "task_1_start", "task_1_end"],
    )


@pytest.mark.asyncio
async def test_semaphore_parallel_profile() -> None:
    """Verify max_concurrency=2 allows 2 workers to execute simultaneously."""
    semaphore = InferenceSemaphore(max_concurrency=2)
    max_observed_concurrency = 0

    async def worker() -> None:
        nonlocal max_observed_concurrency
        async with semaphore.acquire():
            max_observed_concurrency = max(max_observed_concurrency, semaphore.active_workers)
            await asyncio.sleep(0.05)

    await asyncio.gather(worker(), worker())
    assert max_observed_concurrency == 2


@pytest.mark.asyncio
async def test_semaphore_task_reentrancy() -> None:
    """Verify max_concurrency=1 allows reentrant acquisition within the same task."""
    semaphore = InferenceSemaphore(max_concurrency=1)

    async with semaphore.acquire():
        assert semaphore.active_workers == 1
        # Nested acquire within the exact same asyncio task should not block
        async with semaphore.acquire():
            assert semaphore.active_workers == 1
        assert semaphore.active_workers == 1

    assert semaphore.active_workers == 0

