"""
Registry mapping worker_id ↔ Telegram chat_id.
Manager chat IDs are loaded from MANAGER_CHAT_ID: one ID, or several comma-separated.
Workers self-register via /start in the bot.
"""

import os
from app.store import WORKERS


# worker_id → Telegram chat_id
TELEGRAM_REGISTRY: dict[str, int] = {}


def get_manager_chat_ids() -> list[int]:
    """All manager Telegram chat IDs from MANAGER_CHAT_ID (comma-separated allowed)."""
    raw = os.environ.get("MANAGER_CHAT_ID", "").strip()
    if not raw:
        return []
    out: list[int] = []
    seen: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            cid = int(part)
        except ValueError:
            continue
        if cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def get_manager_chat_id() -> int | None:
    """First manager chat ID from environment, or None (backward compatible)."""
    ids = get_manager_chat_ids()
    return ids[0] if ids else None


def register_worker(worker_id: str, chat_id: int) -> bool:
    """
    Map a worker_id to a Telegram chat_id.
    Returns True if successful, False if worker_id is invalid.
    """
    if worker_id not in WORKERS:
        return False
    TELEGRAM_REGISTRY[worker_id] = chat_id
    return True


def unregister_worker(worker_id: str) -> bool:
    """Remove a worker's Telegram mapping."""
    return TELEGRAM_REGISTRY.pop(worker_id, None) is not None


def get_chat_id(worker_id: str) -> int | None:
    """Get the Telegram chat_id for a worker, or None."""
    return TELEGRAM_REGISTRY.get(worker_id)


def get_worker_by_chat(chat_id: int) -> str | None:
    """Reverse lookup: chat_id → worker_id."""
    for wid, cid in TELEGRAM_REGISTRY.items():
        if cid == chat_id:
            return wid
    return None


def get_registered_workers() -> dict[str, int]:
    """Return a copy of all registered workers."""
    return dict(TELEGRAM_REGISTRY)


def is_manager(chat_id: int) -> bool:
    """Check if the given chat_id belongs to a manager."""
    return chat_id in get_manager_chat_ids()
