"""
Registry mapping worker_id ↔ Telegram chat_id.

Household mode: MANAGER_CHAT_ID env var, TELEGRAM_REGISTRY dict.
Shop mode: SHOP_OWNER_CHAT_ID env var, SHOP_TELEGRAM_REGISTRY dict.

Workers/staff self-register via /start or /shopstart in the bot.
"""

import os
from app.store import WORKERS


# ── Household Mode Registry ─────────────────────────────────────────
# worker_id → Telegram chat_id
TELEGRAM_REGISTRY: dict[str, int] = {}

# ── Shop Mode Registry ──────────────────────────────────────────────
# staff_id → Telegram chat_id
SHOP_TELEGRAM_REGISTRY: dict[str, int] = {}


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


# ═══════════════════════════════════════════════════════════════════
# Shop Mode Functions
# ═══════════════════════════════════════════════════════════════════

def _parse_chat_ids(env_var: str) -> list[int]:
    """Parse comma-separated chat IDs from an environment variable."""
    raw = os.environ.get(env_var, "").strip()
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


def get_shop_owner_chat_ids() -> list[int]:
    """Shop owner chat IDs from SHOP_OWNER_CHAT_ID (comma-separated allowed)."""
    return _parse_chat_ids("SHOP_OWNER_CHAT_ID")


def is_shop_owner(chat_id: int) -> bool:
    """Check if the given chat_id belongs to the shop owner."""
    return chat_id in get_shop_owner_chat_ids()


def register_shop_staff(staff_id: str, chat_id: int) -> bool:
    """
    Map a shop staff_id to a Telegram chat_id.
    Returns True if successful, False if staff_id is invalid.
    """
    from app.shop_store import SHOP_STAFF
    if staff_id not in SHOP_STAFF:
        return False
    SHOP_TELEGRAM_REGISTRY[staff_id] = chat_id
    return True


def unregister_shop_staff(staff_id: str) -> bool:
    """Remove a shop staff member's Telegram mapping."""
    return SHOP_TELEGRAM_REGISTRY.pop(staff_id, None) is not None


def get_shop_chat_id(staff_id: str) -> int | None:
    """Get the Telegram chat_id for a shop staff member, or None."""
    return SHOP_TELEGRAM_REGISTRY.get(staff_id)


def get_shop_staff_by_chat(chat_id: int) -> str | None:
    """Reverse lookup: chat_id → shop staff_id."""
    for sid, cid in SHOP_TELEGRAM_REGISTRY.items():
        if cid == chat_id:
            return sid
    return None


def get_registered_shop_staff() -> dict[str, int]:
    """Return a copy of all registered shop staff."""
    return dict(SHOP_TELEGRAM_REGISTRY)

