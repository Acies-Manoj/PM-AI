"""Who is making the current request, available anywhere below the router without passing it
through every function (LLM calls, token accounting, audit logging).

`deps.get_user` sets the user, `deps.load_owned_session` sets the session. Threads started by
a ThreadPoolExecutor do NOT inherit these automatically; wrap the submitted function with
`wrap()` so LLM calls made on worker threads are still attributed to the right user.
"""
from __future__ import annotations

import contextvars
from typing import Callable, TypeVar

T = TypeVar("T")

current_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user_id", default=None)
current_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_session_id", default=None)


def wrap(fn: Callable[..., T]) -> Callable[..., T]:
    """Bind `fn` to a copy of the caller's context: `executor.submit(wrap(fn), *args)`."""
    ctx = contextvars.copy_context()

    def runner(*args, **kwargs) -> T:
        return ctx.run(fn, *args, **kwargs)

    return runner
