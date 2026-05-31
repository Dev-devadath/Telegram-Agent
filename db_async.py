import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="db-worker")


async def db_call(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    loop = asyncio.get_running_loop()
    if kwargs:
        return await loop.run_in_executor(_executor, partial(func, *args, **kwargs))
    return await loop.run_in_executor(_executor, partial(func, *args))


def shutdown_executor() -> None:
    _executor.shutdown(wait=False, cancel_futures=True)
