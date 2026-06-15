import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Iterator
import unicodedata

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from config import (
    ADMIN_TELEGRAM_ID,
    DATABASE_URL,
    DB_POOL_MAX_SIZE,
    DB_POOL_MIN_SIZE,
    DB_POOL_TIMEOUT,
)

DEFAULT_ROLES = ["Driver", "Cook", "Cleaner", "Security"]


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _normalize_password(password: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(password or ""))
    return "".join(normalized.split())


def _is_env_admin(telegram_id: int) -> bool:
    return bool(ADMIN_TELEGRAM_ID and telegram_id == ADMIN_TELEGRAM_ID)


def _admin_user() -> dict[str, Any]:
    return {
        "id": "env_admin",
        "telegram_id": ADMIN_TELEGRAM_ID,
        "name": "Admin",
        "role": "admin",
        "worker_role": None,
        "owner_id": None,
        "manager_password": None,
        "points": 0,
        "active": True,
        "created_at": None,
    }


_pool: ConnectionPool | None = None


def _pool_kwargs() -> dict[str, Any]:
    return {
        "row_factory": dict_row,
        "sslmode": "require",
        "prepare_threshold": None,
    }


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL is required. Set it to your Supabase Postgres connection string."
            )
        _pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=DB_POOL_MIN_SIZE,
            max_size=DB_POOL_MAX_SIZE,
            timeout=DB_POOL_TIMEOUT,
            kwargs=_pool_kwargs(),
            open=True,
        )
    return _pool


@contextmanager
def _connect() -> Iterator[Any]:
    with _get_pool().connection() as conn:
        yield conn


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def _run_schema(conn) -> None:
    conn.execute(
        """
        create table if not exists app_settings (
            id boolean primary key default true check (id),
            test_mode boolean not null default false,
            test_telegram_id bigint
        );

        create table if not exists users (
            id text primary key,
            telegram_id bigint not null,
            name text not null,
            role text not null check (role in ('admin', 'owner', 'manager', 'worker')),
            worker_role text,
            owner_id text references users(id) on delete set null,
            manager_password text,
            points integer not null default 0,
            active boolean not null default true,
            created_at text not null,
            fired_at text,
            fired_by_manager_id text,
            fired_reason text,
            removed_at text,
            removed_by_admin_reason text
        );

        create table if not exists roles (
            name text primary key,
            manager_id text references users(id) on delete set null
        );

        create table if not exists tasks (
            id text primary key,
            title text not null,
            description text not null,
            worker_role text not null,
            manager_id text not null references users(id) on delete cascade,
            depends_on_task_id text references tasks(id) on delete set null,
            time text not null,
            scheduled_date text,
            recurrence text not null default 'daily',
            weekday integer,
            no_penalty boolean not null default false,
            active boolean not null default true,
            created_at text not null,
            deleted_at text,
            deleted_by_manager_id text,
            disabled_at text,
            disabled_reason text
        );

        create table if not exists task_runs (
            id text primary key,
            task_id text not null references tasks(id) on delete cascade,
            worker_role text not null,
            manager_id text not null references users(id) on delete cascade,
            scheduled_for text not null,
            status text not null,
            worker_response text,
            reason text,
            worker_note text,
            manager_status text not null default 'pending',
            created_at text not null,
            completed_at text,
            verified_at text
        );

        alter table users add column if not exists points integer not null default 0;
        alter table users add column if not exists owner_id text references users(id) on delete set null;
        alter table users drop constraint if exists users_role_check;
        alter table users add constraint users_role_check
            check (role in ('admin', 'owner', 'manager', 'worker'));
        alter table tasks add column if not exists scheduled_date text;
        alter table tasks add column if not exists depends_on_task_id text references tasks(id) on delete set null;
        alter table tasks add column if not exists no_penalty boolean not null default false;
        alter table task_runs add column if not exists worker_note text;

        create table if not exists firings (
            id text primary key,
            worker_id text not null,
            worker_name text,
            worker_role text,
            worker_telegram_id bigint,
            manager_id text not null,
            reason text not null,
            points_delta integer not null default -2,
            created_at text not null
        );

        alter table firings add column if not exists points_delta integer not null default -2;

        create unique index if not exists users_active_manager_password_idx
            on users(manager_password)
            where role = 'manager' and active = true and manager_password is not null;
        create unique index if not exists users_active_worker_role_idx
            on users(worker_role)
            where role = 'worker' and active = true and worker_role is not null;
        create index if not exists users_active_owner_idx on users(owner_id)
            where active = true;
        create index if not exists tasks_active_manager_idx on tasks(manager_id, active);
        create index if not exists task_runs_report_idx on task_runs(worker_role, created_at);
        create index if not exists users_active_telegram_idx
            on users(telegram_id)
            where active = true;
        create index if not exists users_active_telegram_role_idx
            on users(telegram_id, role)
            where active = true;
        create index if not exists tasks_dependent_parent_idx
            on tasks(depends_on_task_id)
            where active = true and recurrence = 'after_task';
        create index if not exists task_runs_manager_created_idx
            on task_runs(manager_id, created_at);
        create index if not exists task_runs_task_created_idx
            on task_runs(task_id, created_at);
        create index if not exists task_runs_manager_role_created_idx
            on task_runs(manager_id, worker_role, created_at);

        alter table app_settings enable row level security;
        alter table users enable row level security;
        alter table roles enable row level security;
        alter table tasks enable row level security;
        alter table task_runs enable row level security;
        alter table firings enable row level security;
        """
    )
    conn.execute(
        """
        insert into app_settings (id, test_mode, test_telegram_id)
        values (true, false, null)
        on conflict (id) do nothing
        """
    )


def _ensure_defaults(conn) -> None:
    for role in DEFAULT_ROLES:
        conn.execute(
            "insert into roles (name, manager_id) values (%s, null) on conflict (name) do nothing",
            (role,),
        )

    # Admin identity is configuration-only. Remove older DB-backed admin rows.
    conn.execute("delete from users where role = 'admin'")
    managers = conn.execute(
        """
        select id, manager_password from users
        where role = 'manager' and manager_password is not null
        """
    ).fetchall()
    for manager in managers:
        normalized_password = _normalize_password(manager["manager_password"])
        if normalized_password != manager["manager_password"]:
            conn.execute(
                "update users set manager_password = %s where id = %s",
                (normalized_password, manager["id"]),
            )


def ensure_data_file() -> None:
    """Initialize Supabase/Postgres tables.

    The old name is kept so the rest of the bot startup code does not need to change.
    """
    with _connect() as conn:
        _run_schema(conn)
        _ensure_defaults(conn)


def get_settings() -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute(
            "select test_mode, test_telegram_id from app_settings where id = true"
        ).fetchone()
    return {
        "test_mode": bool(row["test_mode"]) if row else False,
        "test_telegram_id": row["test_telegram_id"] if row else None,
    }


def set_test_mode(enabled: bool, telegram_id: int | None) -> dict[str, Any]:
    with _connect() as conn:
        conn.execute(
            """
            insert into app_settings (id, test_mode, test_telegram_id)
            values (true, %s, %s)
            on conflict (id) do update
            set test_mode = excluded.test_mode,
                test_telegram_id = excluded.test_telegram_id
            """,
            (enabled, telegram_id),
        )
    return get_settings()


def map_all_workers_to_telegram(telegram_id: int) -> int:
    with _connect() as conn:
        result = conn.execute(
            """
            update users
            set telegram_id = %s
            where role = 'worker' and active = true and telegram_id <> %s
            """,
            (telegram_id, telegram_id),
        )
        return result.rowcount or 0


def get_user_by_telegram(telegram_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        user = conn.execute(
            "select * from users where telegram_id = %s and active = true limit 1",
            (telegram_id,),
        ).fetchone()
    if user:
        return user
    if _is_env_admin(telegram_id):
        return _admin_user()
    return None


def list_users_by_telegram(telegram_id: int) -> list[dict[str, Any]]:
    with _connect() as conn:
        users = conn.execute(
            "select * from users where telegram_id = %s and active = true order by created_at",
            (telegram_id,),
        ).fetchall()
    if _is_env_admin(telegram_id):
        users.append(_admin_user())
    return users


def telegram_has_role(telegram_id: int, role: str) -> bool:
    if role == "admin":
        return _is_env_admin(telegram_id)
    with _connect() as conn:
        row = conn.execute(
            """
            select 1 from users
            where telegram_id = %s and role = %s and active = true
            limit 1
            """,
            (telegram_id, role),
        ).fetchone()
    return row is not None


def telegram_has_any_role(telegram_id: int, roles: list[str]) -> bool:
    if "admin" in roles and _is_env_admin(telegram_id):
        return True
    db_roles = [role for role in roles if role != "admin"]
    if not db_roles:
        return False
    with _connect() as conn:
        row = conn.execute(
            """
            select 1 from users
            where telegram_id = %s
              and role = any(%s)
              and active = true
            limit 1
            """,
            (telegram_id, db_roles),
        ).fetchone()
    return row is not None


def get_user_by_telegram_and_role(telegram_id: int, role: str) -> dict[str, Any] | None:
    if role == "admin" and _is_env_admin(telegram_id):
        return _admin_user()
    with _connect() as conn:
        return conn.execute(
            """
            select * from users
            where telegram_id = %s and role = %s and active = true
            limit 1
            """,
            (telegram_id, role),
        ).fetchone()


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        return conn.execute(
            "select * from users where id = %s and active = true",
            (user_id,),
        ).fetchone()


def get_user_by_role(worker_role: str) -> dict[str, Any] | None:
    with _connect() as conn:
        return conn.execute(
            """
            select * from users
            where role = 'worker' and worker_role = %s and active = true
            limit 1
            """,
            (worker_role,),
        ).fetchone()


def list_users_by_role(role: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        return conn.execute(
            "select * from users where role = %s and active = true order by created_at",
            (role,),
        ).fetchall()


def assign_manager_to_owner(manager_id: str, owner_id: str) -> dict[str, Any]:
    with _connect() as conn:
        owner = conn.execute(
            "select * from users where id = %s and role = 'owner' and active = true",
            (owner_id,),
        ).fetchone()
        if not owner:
            raise ValueError("Owner not found.")

        manager = conn.execute(
            """
            update users
            set owner_id = %s
            where id = %s and role = 'manager' and active = true
            returning *
            """,
            (owner_id, manager_id),
        ).fetchone()
        if not manager:
            raise ValueError("Manager not found.")
        return manager


def list_managers_for_owner(owner_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        return conn.execute(
            """
            select * from users
            where role = 'manager' and active = true and owner_id = %s
            order by name, created_at
            """,
            (owner_id,),
        ).fetchall()


def list_workers_under_manager(manager_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        return conn.execute(
            """
            select distinct u.*
            from users u
            where u.role = 'worker'
              and u.active = true
              and u.worker_role in (
                select name from roles where manager_id = %s
                union
                select worker_role from tasks where manager_id = %s and active = true
              )
            order by u.worker_role, u.name
            """,
            (manager_id, manager_id),
        ).fetchall()


def list_workers_under_owner(owner_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        return conn.execute(
            """
            select distinct u.*
            from users u
            where u.role = 'worker'
              and u.active = true
              and u.worker_role in (
                select r.name
                from roles r
                join users m on m.id = r.manager_id
                where m.role = 'manager' and m.active = true and m.owner_id = %s
                union
                select t.worker_role
                from tasks t
                join users m on m.id = t.manager_id
                where t.active = true
                  and m.role = 'manager'
                  and m.active = true
                  and m.owner_id = %s
              )
            order by u.worker_role, u.name
            """,
            (owner_id, owner_id),
        ).fetchall()


def adjust_worker_points(worker_id: str, delta: int) -> dict[str, Any]:
    with _connect() as conn:
        worker = conn.execute(
            """
            update users
            set points = points + %s
            where id = %s and role = 'worker' and active = true
            returning *
            """,
            (delta, worker_id),
        ).fetchone()
        if not worker:
            raise ValueError("Active worker not found.")
        return worker


def list_roles() -> list[str]:
    with _connect() as conn:
        rows = conn.execute("select name from roles order by name").fetchall()
    return [row["name"] for row in rows]


def list_roles_for_manager(manager_id: str) -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            "select name from roles where manager_id = %s order by name",
            (manager_id,),
        ).fetchall()
    return [row["name"] for row in rows]


def list_roles_for_owner(owner_id: str) -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            """
            select distinct r.name
            from roles r
            join users m on m.id = r.manager_id
            where m.role = 'manager'
              and m.active = true
              and m.owner_id = %s
            order by r.name
            """,
            (owner_id,),
        ).fetchall()
    return [row["name"] for row in rows]


def get_manager_by_password(password: str) -> dict[str, Any] | None:
    password = _normalize_password(password)
    if not password:
        return None
    with _connect() as conn:
        return conn.execute(
            """
            select * from users
            where role = 'manager'
              and active = true
              and manager_password = %s
            limit 1
            """,
            (password,),
        ).fetchone()


def get_unclaimed_roles_for_manager(manager_id: str) -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            """
            select r.name
            from roles r
            left join users u
              on u.role = 'worker'
             and u.worker_role = r.name
             and u.active = true
            where r.manager_id = %s
              and u.id is null
            order by r.name
            """,
            (manager_id,),
        ).fetchall()
    return [row["name"] for row in rows]


def _ensure_telegram_available_for_role(
    conn,
    telegram_id: int,
    role: str,
    exclude_user_id: str | None = None,
) -> None:
    same_role_query = """
        select 1 from users
        where telegram_id = %s and role = %s and active = true
    """
    same_role_params: list[Any] = [telegram_id, role]
    if exclude_user_id:
        same_role_query += " and id <> %s"
        same_role_params.append(exclude_user_id)
    same_role_query += " limit 1"
    if conn.execute(same_role_query, same_role_params).fetchone():
        raise ValueError(f"Telegram ID is already registered as {role}.")

    settings = get_settings()
    any_query = "select id from users where telegram_id = %s and active = true"
    any_params: list[Any] = [telegram_id]
    if exclude_user_id:
        any_query += " and id <> %s"
        any_params.append(exclude_user_id)
    any_query += " limit 1"
    existing_any = conn.execute(any_query, any_params).fetchone()
    if not settings.get("test_mode"):
        if existing_any:
            raise ValueError("Telegram ID already registered.")
    elif existing_any and telegram_id != settings.get("test_telegram_id"):
        raise ValueError("Telegram ID already registered.")


def update_manager_password(manager_id: str, password: str) -> dict[str, Any]:
    return update_manager(manager_id, password=password)


def update_manager(
    manager_id: str,
    name: str | None = None,
    telegram_id: int | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if name is not None:
        name = name.strip()
        if not name:
            raise ValueError("Manager name cannot be empty.")
        updates["name"] = name
    if telegram_id is not None:
        updates["telegram_id"] = telegram_id
    if password is not None:
        password = _normalize_password(password)
        if not password:
            raise ValueError("Manager password is required.")
        updates["manager_password"] = password

    if not updates:
        manager = get_user_by_id(manager_id)
        if not manager or manager.get("role") != "manager":
            raise ValueError("Manager not found.")
        return manager

    with _connect() as conn:
        manager = conn.execute(
            "select * from users where id = %s and role = 'manager' and active = true",
            (manager_id,),
        ).fetchone()
        if not manager:
            raise ValueError("Manager not found.")

        if telegram_id is not None:
            _ensure_telegram_available_for_role(
                conn, telegram_id, "manager", exclude_user_id=manager_id
            )

        if password is not None:
            password_taken = conn.execute(
                """
                select 1 from users
                where id <> %s
                  and role = 'manager'
                  and active = true
                  and manager_password = %s
                limit 1
                """,
                (manager_id, password),
            ).fetchone()
            if password_taken:
                raise ValueError("Manager password is already used.")

        assignments = ", ".join(f"{field} = %s" for field in updates)
        values = [updates[field] for field in updates]
        values.append(manager_id)
        return conn.execute(
            f"update users set {assignments} where id = %s returning *",
            values,
        ).fetchone()


def update_owner(
    owner_id: str,
    name: str | None = None,
    telegram_id: int | None = None,
) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if name is not None:
        name = name.strip()
        if not name:
            raise ValueError("Owner name cannot be empty.")
        updates["name"] = name
    if telegram_id is not None:
        updates["telegram_id"] = telegram_id

    if not updates:
        owner = get_user_by_id(owner_id)
        if not owner or owner.get("role") != "owner":
            raise ValueError("Owner not found.")
        return owner

    with _connect() as conn:
        owner = conn.execute(
            "select * from users where id = %s and role = 'owner' and active = true",
            (owner_id,),
        ).fetchone()
        if not owner:
            raise ValueError("Owner not found.")

        if telegram_id is not None:
            _ensure_telegram_available_for_role(
                conn, telegram_id, "owner", exclude_user_id=owner_id
            )

        assignments = ", ".join(f"{field} = %s" for field in updates)
        values = [updates[field] for field in updates]
        values.append(owner_id)
        return conn.execute(
            f"update users set {assignments} where id = %s returning *",
            values,
        ).fetchone()


def remove_owner(owner_id: str) -> dict[str, Any]:
    with _connect() as conn:
        owner = conn.execute(
            "select * from users where id = %s and role = 'owner' and active = true",
            (owner_id,),
        ).fetchone()
        if not owner:
            raise ValueError("Active owner not found.")

        removed_at = _now_iso()
        conn.execute(
            """
            update users
            set owner_id = null
            where role = 'manager' and active = true and owner_id = %s
            """,
            (owner_id,),
        )
        conn.execute(
            """
            update users
            set active = false,
                removed_at = %s,
                removed_by_admin_reason = 'Removed by admin'
            where id = %s
            """,
            (removed_at, owner_id),
        )
        return owner


def add_role(role_name: str, manager_id: str | None = None) -> None:
    role_name = role_name.strip()
    if not role_name:
        raise ValueError("Role cannot be empty.")

    with _connect() as conn:
        if manager_id:
            manager = conn.execute(
                "select * from users where id = %s and role = 'manager' and active = true",
                (manager_id,),
            ).fetchone()
            if not manager:
                raise ValueError("Invalid manager.")

        try:
            conn.execute(
                "insert into roles (name, manager_id) values (%s, %s)",
                (role_name, manager_id),
            )
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("Role already exists.") from exc


def remove_role(role_name: str) -> None:
    with _connect() as conn:
        role = conn.execute("select * from roles where name = %s", (role_name,)).fetchone()
        if not role:
            raise ValueError("Role not found.")
        claimed = conn.execute(
            """
            select 1 from users
            where role = 'worker' and worker_role = %s and active = true
            limit 1
            """,
            (role_name,),
        ).fetchone()
        if claimed:
            raise ValueError("Role is already claimed by a worker.")
        conn.execute("delete from roles where name = %s", (role_name,))


def get_unclaimed_roles() -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            """
            select r.name
            from roles r
            left join users u
              on u.role = 'worker'
             and u.worker_role = r.name
             and u.active = true
            where u.id is null
            order by r.name
            """
        ).fetchall()
    return [row["name"] for row in rows]


def add_user(
    telegram_id: int,
    name: str,
    system_role: str,
    worker_role: str | None = None,
    manager_password: str | None = None,
) -> dict[str, Any]:
    with _connect() as conn:
        existing_same_role = conn.execute(
            """
            select 1 from users
            where telegram_id = %s and role = %s and active = true
            limit 1
            """,
            (telegram_id, system_role),
        ).fetchone()
        if existing_same_role:
            raise ValueError(f"Telegram ID is already registered as {system_role}.")

        settings = get_settings()
        existing_any = conn.execute(
            "select 1 from users where telegram_id = %s and active = true limit 1",
            (telegram_id,),
        ).fetchone()
        if not settings.get("test_mode"):
            if existing_any:
                raise ValueError("Telegram ID already registered.")
        elif existing_any and telegram_id != settings.get("test_telegram_id"):
            raise ValueError("Telegram ID already registered.")

        if system_role == "worker":
            if not worker_role:
                raise ValueError("Worker role is required.")
            role = conn.execute("select * from roles where name = %s", (worker_role,)).fetchone()
            if not role:
                raise ValueError("Worker role does not exist.")
            claimed = conn.execute(
                """
                select 1 from users
                where role = 'worker' and worker_role = %s and active = true
                limit 1
                """,
                (worker_role,),
            ).fetchone()
            if claimed:
                raise ValueError("This role is already claimed.")

        if system_role == "manager":
            manager_password = _normalize_password(manager_password or "")
            if not manager_password:
                raise ValueError("Manager password is required.")
            password_taken = conn.execute(
                """
                select 1 from users
                where role = 'manager' and active = true and manager_password = %s
                limit 1
                """,
                (manager_password,),
            ).fetchone()
            if password_taken:
                raise ValueError("Manager password is already used.")

        user = conn.execute(
            """
            insert into users (
                id, telegram_id, name, role, worker_role, manager_password,
                points, active, created_at
            )
            values (%s, %s, %s, %s, %s, %s, 0, true, %s)
            returning *
            """,
            (
                _new_id("u"),
                telegram_id,
                name.strip() or system_role.title(),
                system_role,
                worker_role,
                manager_password if system_role == "manager" else None,
                _now_iso(),
            ),
        ).fetchone()
        return user


def add_task(
    title: str,
    description: str,
    worker_role: str,
    manager_id: str,
    time_hhmm: str,
    recurrence: str = "daily",
    weekday: int | None = None,
    scheduled_date: str | None = None,
    depends_on_task_id: str | None = None,
    no_penalty: bool = False,
) -> dict[str, Any]:
    with _connect() as conn:
        role = conn.execute("select * from roles where name = %s", (worker_role,)).fetchone()
        if not role:
            raise ValueError("Unknown worker role.")

        manager = conn.execute(
            "select * from users where id = %s and role = 'manager' and active = true",
            (manager_id,),
        ).fetchone()
        if not manager:
            raise ValueError("Invalid manager.")

        if role.get("manager_id") and role["manager_id"] != manager_id:
            raise ValueError("This role belongs to another manager.")
        if not role.get("manager_id"):
            conn.execute(
                "update roles set manager_id = %s where name = %s",
                (manager_id, worker_role),
            )

        if recurrence == "after_task":
            if not depends_on_task_id:
                raise ValueError("Parent task is required for dependent scheduling.")
            parent_task = conn.execute(
                """
                select *
                from tasks
                where id = %s and manager_id = %s and active = true
                limit 1
                """,
                (depends_on_task_id, manager_id),
            ).fetchone()
            if not parent_task:
                raise ValueError("Parent task not found under this manager.")
            time_hhmm = "00:00"
            scheduled_date = None
            weekday = None
        elif depends_on_task_id:
            raise ValueError("Parent task can be set only for dependent scheduling.")

        task = conn.execute(
            """
            insert into tasks (
                id, title, description, worker_role, manager_id, depends_on_task_id, time,
                scheduled_date, recurrence, weekday, no_penalty, active, created_at
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s)
            returning *
            """,
            (
                _new_id("t"),
                title.strip(),
                description.strip(),
                worker_role,
                manager_id,
                depends_on_task_id if recurrence == "after_task" else None,
                time_hhmm,
                scheduled_date,
                recurrence,
                weekday,
                no_penalty,
                _now_iso(),
            ),
        ).fetchone()
        return task


def fire_worker(worker_id: str, manager_id: str, reason: str) -> dict[str, Any]:
    with _connect() as conn:
        worker = conn.execute(
            "select * from users where id = %s and role = 'worker' and active = true",
            (worker_id,),
        ).fetchone()
        if not worker:
            raise ValueError("Active worker not found.")

        managed_role = conn.execute(
            """
            select 1
            where %s in (
                select name from roles where manager_id = %s
                union
                select worker_role from tasks where manager_id = %s and active = true
            )
            """,
            (worker["worker_role"], manager_id, manager_id),
        ).fetchone()
        if not managed_role:
            raise ValueError("This worker is not under this manager.")

        fired_at = _now_iso()
        firing = conn.execute(
            """
            insert into firings (
                id, worker_id, worker_name, worker_role, worker_telegram_id,
                manager_id, reason, points_delta, created_at
            )
            values (%s, %s, %s, %s, %s, %s, %s, -2, %s)
            returning *
            """,
            (
                _new_id("f"),
                worker_id,
                worker["name"],
                worker["worker_role"],
                worker["telegram_id"],
                manager_id,
                reason.strip(),
                fired_at,
            ),
        ).fetchone()
        conn.execute(
            """
            update users
            set fired_at = %s,
                fired_by_manager_id = %s,
                fired_reason = %s,
                points = points - 2
            where id = %s
            """,
            (fired_at, manager_id, reason.strip(), worker_id),
        )
        updated_worker = conn.execute(
            "select * from users where id = %s",
            (worker_id,),
        ).fetchone()
        firing["worker_points"] = updated_worker["points"] if updated_worker else None
        return firing


def remove_manager(manager_id: str) -> dict[str, Any]:
    with _connect() as conn:
        manager = conn.execute(
            "select * from users where id = %s and role = 'manager' and active = true",
            (manager_id,),
        ).fetchone()
        if not manager:
            raise ValueError("Active manager not found.")

        owned_roles = {
            row["name"]
            for row in conn.execute(
                "select name from roles where manager_id = %s",
                (manager_id,),
            ).fetchall()
        }
        task_roles = {
            row["worker_role"]
            for row in conn.execute(
                "select worker_role from tasks where manager_id = %s and active = true",
                (manager_id,),
            ).fetchall()
        }
        affected_roles = owned_roles | task_roles
        removed_at = _now_iso()

        removed_workers: list[dict[str, Any]] = []
        if affected_roles:
            removed_workers = conn.execute(
                """
                select * from users
                where role = 'worker' and active = true and worker_role = any(%s)
                """,
                (list(affected_roles),),
            ).fetchall()
            conn.execute(
                """
                update users
                set active = false,
                    removed_at = %s,
                    removed_by_admin_reason = 'Manager removed'
                where role = 'worker' and active = true and worker_role = any(%s)
                """,
                (removed_at, list(affected_roles)),
            )

        disabled = conn.execute(
            """
            update tasks
            set active = false,
                disabled_at = %s,
                disabled_reason = 'Manager removed'
            where active = true
              and (manager_id = %s or worker_role = any(%s))
            """,
            (removed_at, manager_id, list(affected_roles)),
        )
        disabled_tasks = disabled.rowcount or 0

        conn.execute(
            """
            update users
            set active = false,
                removed_at = %s,
                removed_by_admin_reason = 'Removed by admin'
            where id = %s
            """,
            (removed_at, manager_id),
        )
        if owned_roles:
            conn.execute("delete from roles where name = any(%s)", (list(owned_roles),))

        return {
            "manager": manager,
            "removed_workers": removed_workers,
            "removed_roles": sorted(owned_roles),
            "disabled_tasks": disabled_tasks,
        }


def list_active_tasks() -> list[dict[str, Any]]:
    with _connect() as conn:
        return conn.execute(
            "select * from tasks where active = true order by created_at"
        ).fetchall()


def list_tasks_for_admin() -> list[dict[str, Any]]:
    with _connect() as conn:
        return conn.execute(
            """
            select
                t.*,
                parent.title as parent_task_title,
                coalesce(u.name, 'Unassigned') as worker_name,
                u.telegram_id as worker_telegram_id,
                m.name as manager_name
            from tasks t
            left join tasks parent
              on parent.id = t.depends_on_task_id
            join users m
              on m.id = t.manager_id
             and m.role = 'manager'
             and m.active = true
            left join users u
              on u.role = 'worker'
             and u.worker_role = t.worker_role
             and u.active = true
            where t.active = true
            order by m.name, t.created_at
            """
        ).fetchall()


def list_parent_task_options(manager_id: str | None = None) -> list[dict[str, Any]]:
    query = """
        select t.id, t.title, t.worker_role, t.manager_id
        from tasks t
        where t.active = true
          and t.recurrence <> 'after_task'
    """
    params: list[Any] = []
    if manager_id:
        query += " and t.manager_id = %s"
        params.append(manager_id)
    query += " order by t.created_at"

    with _connect() as conn:
        return conn.execute(query, params).fetchall()


def list_dependent_tasks(parent_task_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        return conn.execute(
            """
            select *
            from tasks
            where active = true
              and recurrence = 'after_task'
              and depends_on_task_id = %s
            order by created_at
            """,
            (parent_task_id,),
        ).fetchall()


def list_tasks_for_manager(manager_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        return conn.execute(
            """
            select
                t.*,
                parent.title as parent_task_title,
                coalesce(u.name, 'Unassigned') as worker_name,
                u.telegram_id as worker_telegram_id
            from tasks t
            left join tasks parent
              on parent.id = t.depends_on_task_id
            left join users u
              on u.role = 'worker'
             and u.worker_role = t.worker_role
             and u.active = true
            where t.manager_id = %s and t.active = true
            order by t.created_at
            """,
            (manager_id,),
        ).fetchall()


def list_tasks_for_owner(owner_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        return conn.execute(
            """
            select
                t.*,
                parent.title as parent_task_title,
                coalesce(u.name, 'Unassigned') as worker_name,
                u.telegram_id as worker_telegram_id,
                m.name as manager_name
            from tasks t
            left join tasks parent
              on parent.id = t.depends_on_task_id
            join users m
              on m.id = t.manager_id
             and m.role = 'manager'
             and m.active = true
             and m.owner_id = %s
            left join users u
              on u.role = 'worker'
             and u.worker_role = t.worker_role
             and u.active = true
            where t.active = true
            order by m.name, t.created_at
            """,
            (owner_id,),
        ).fetchall()


def get_task_by_id(task_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        return conn.execute("select * from tasks where id = %s", (task_id,)).fetchone()


def update_task(task_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "title",
        "description",
        "worker_role",
        "manager_id",
        "depends_on_task_id",
        "time",
        "scheduled_date",
        "recurrence",
        "weekday",
        "no_penalty",
        "active",
        "deleted_at",
        "deleted_by_manager_id",
        "disabled_at",
        "disabled_reason",
    }
    fields = [field for field in updates if field in allowed]
    if not fields:
        task = get_task_by_id(task_id)
        if not task:
            raise ValueError("Task not found.")
        return task

    assignments = ", ".join(f"{field} = %s" for field in fields)
    values = [updates[field] for field in fields]
    values.append(task_id)
    with _connect() as conn:
        task = conn.execute(
            f"update tasks set {assignments} where id = %s returning *",
            values,
        ).fetchone()
        if not task:
            raise ValueError("Task not found.")
        return task


def deactivate_manager_task(task_id: str, manager_id: str) -> dict[str, Any]:
    with _connect() as conn:
        task = conn.execute("select * from tasks where id = %s", (task_id,)).fetchone()
        if not task:
            raise ValueError("Task not found.")
        if task["manager_id"] != manager_id:
            raise ValueError("Task does not belong to this manager.")
        if not task.get("active", True):
            raise ValueError("Task is already deleted.")

        return conn.execute(
            """
            update tasks
            set active = false,
                deleted_at = %s,
                deleted_by_manager_id = %s
            where id = %s
            returning *
            """,
            (_now_iso(), manager_id, task_id),
        ).fetchone()


def add_task_run(task: dict[str, Any], scheduled_for: str) -> dict[str, Any]:
    with _connect() as conn:
        return conn.execute(
            """
            insert into task_runs (
                id, task_id, worker_role, manager_id, scheduled_for, status,
                worker_response, reason, worker_note, manager_status,
                created_at, completed_at, verified_at
            )
            values (%s, %s, %s, %s, %s, 'sent_to_worker', null, null, null, 'pending', %s, null, null)
            returning *
            """,
            (
                _new_id("r"),
                task["id"],
                task["worker_role"],
                task["manager_id"],
                scheduled_for,
                _now_iso(),
            ),
        ).fetchone()


def get_task_run(run_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        return conn.execute("select * from task_runs where id = %s", (run_id,)).fetchone()


def update_task_run(run_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "task_id",
        "worker_role",
        "manager_id",
        "scheduled_for",
        "status",
        "worker_response",
        "reason",
        "worker_note",
        "manager_status",
        "completed_at",
        "verified_at",
    }
    fields = [field for field in updates if field in allowed]
    if not fields:
        run = get_task_run(run_id)
        if not run:
            raise ValueError("Task run not found.")
        return run

    assignments = ", ".join(f"{field} = %s" for field in fields)
    values = [updates[field] for field in fields]
    values.append(run_id)
    with _connect() as conn:
        run = conn.execute(
            f"update task_runs set {assignments} where id = %s returning *",
            values,
        ).fetchone()
        if not run:
            raise ValueError("Task run not found.")
        return run


def get_runs_for_report(
    worker_role: str | None = None,
    period: str = "today",
    manager_id: str | None = None,
    owner_id: str | None = None,
) -> list[dict[str, Any]]:
    now = datetime.utcnow()
    from_time: datetime | None = None
    if period == "today":
        from_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        from_time = now - timedelta(days=7)
    elif period == "month":
        from_time = now - timedelta(days=30)

    query = "select * from task_runs where true"
    params: list[Any] = []
    if worker_role:
        query += " and worker_role = %s"
        params.append(worker_role)
    if manager_id:
        query += " and manager_id = %s"
        params.append(manager_id)
    if owner_id:
        query += (
            " and manager_id in ("
            "select id from users "
            "where role = 'manager' and active = true and owner_id = %s"
            ")"
        )
        params.append(owner_id)
    if from_time:
        query += " and created_at >= %s"
        params.append(from_time.replace(microsecond=0).isoformat())
    query += " order by created_at desc"

    with _connect() as conn:
        return conn.execute(query, params).fetchall()


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(runs),
        "verified": sum(1 for run in runs if run.get("status") == "manager_verified"),
        "not_completed": sum(1 for run in runs if run.get("status") == "worker_not_done"),
        "rejected": sum(1 for run in runs if run.get("status") == "manager_rejected"),
        "extended": sum(1 for run in runs if run.get("status") == "extended"),
    }


def _report_from_time(period: str) -> datetime | None:
    now = datetime.utcnow()
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        return now - timedelta(days=7)
    if period == "month":
        return now - timedelta(days=30)
    return None


def _report_filter_clause(
    worker_role: str | None,
    period: str,
    manager_id: str | None,
    owner_id: str | None,
) -> tuple[str, list[Any]]:
    query = " where true"
    params: list[Any] = []
    if worker_role:
        query += " and tr.worker_role = %s"
        params.append(worker_role)
    if manager_id:
        query += " and tr.manager_id = %s"
        params.append(manager_id)
    if owner_id:
        query += (
            " and tr.manager_id in ("
            "select id from users "
            "where role = 'manager' and active = true and owner_id = %s"
            ")"
        )
        params.append(owner_id)
    if period == "pending":
        query += " and tr.worker_response is null and tr.status = 'sent_to_worker'"
    from_time = _report_from_time(period)
    if from_time:
        query += " and tr.created_at >= %s"
        params.append(from_time.replace(microsecond=0).isoformat())
    return query, params


def get_report_summary(
    worker_role: str | None = None,
    period: str = "today",
    manager_id: str | None = None,
    owner_id: str | None = None,
    top_tasks: int = 50,
) -> dict[str, Any]:
    filter_clause, params = _report_filter_clause(
        worker_role, period, manager_id, owner_id
    )
    with _connect() as conn:
        stats_row = conn.execute(
            f"""
            select
                count(*) as total,
                count(*) filter (where tr.status = 'manager_verified') as verified,
                count(*) filter (where tr.status = 'worker_not_done') as not_completed,
                count(*) filter (where tr.status = 'manager_rejected') as rejected,
                count(*) filter (where tr.status = 'extended') as extended,
                count(*) filter (where tr.worker_response = 'yes') as yes_count,
                count(*) filter (where tr.worker_response = 'no') as no_count,
                count(*) filter (where tr.worker_response = 'extend') as extend_count,
                count(*) filter (where tr.worker_response is null) as pending_response_count,
                count(*) filter (
                    where tr.worker_response in ('yes', 'no')
                      and tr.manager_status = 'pending'
                ) as pending_manager_count
            from task_runs tr
            {filter_clause}
            """,
            params,
        ).fetchone()

        task_metrics = conn.execute(
            f"""
            select
                tr.task_id,
                coalesce(t.title, 'Unknown Task') as title,
                coalesce(t.description, '') as description,
                coalesce(t.no_penalty, false) as no_penalty,
                count(*) as total,
                count(*) filter (where tr.status = 'manager_verified') as verified,
                count(*) filter (where tr.worker_response = 'no') as not_done,
                count(*) filter (where tr.worker_response is null) as pending_response,
                count(*) filter (where tr.status = 'manager_rejected') as rejected,
                count(*) filter (
                    where tr.worker_response in ('yes', 'no')
                      and tr.manager_status = 'pending'
                ) as pending_manager
            from task_runs tr
            left join tasks t on t.id = tr.task_id
            {filter_clause}
            group by tr.task_id, t.title, t.description, t.no_penalty
            order by count(*) desc
            limit %s
            """,
            [*params, top_tasks + 1],
        ).fetchall()

        total_task_groups = conn.execute(
            f"""
            select count(*) as group_count
            from (
                select tr.task_id
                from task_runs tr
                {filter_clause}
                group by tr.task_id
            ) grouped_tasks
            """,
            params,
        ).fetchone()

        if worker_role:
            workers = conn.execute(
                """
                select name, worker_role, points
                from users
                where role = 'worker' and active = true and worker_role = %s
                order by name
                """,
                (worker_role,),
            ).fetchall()
        elif manager_id:
            workers = conn.execute(
                """
                select distinct u.name, u.worker_role, u.points
                from users u
                where u.role = 'worker'
                  and u.active = true
                  and u.worker_role in (
                    select name from roles where manager_id = %s
                    union
                    select worker_role from tasks where manager_id = %s and active = true
                  )
                order by u.worker_role, u.name
                """,
                (manager_id, manager_id),
            ).fetchall()
        elif owner_id:
            workers = conn.execute(
                """
                select distinct u.name, u.worker_role, u.points
                from users u
                where u.role = 'worker'
                  and u.active = true
                  and u.worker_role in (
                    select r.name
                    from roles r
                    join users m on m.id = r.manager_id
                    where m.role = 'manager' and m.active = true and m.owner_id = %s
                    union
                    select t.worker_role
                    from tasks t
                    join users m on m.id = t.manager_id
                    where t.active = true
                      and m.role = 'manager'
                      and m.active = true
                      and m.owner_id = %s
                  )
                order by u.worker_role, u.name
                """,
                (owner_id, owner_id),
            ).fetchall()
        else:
            workers = conn.execute(
                """
                select name, worker_role, points
                from users
                where role = 'worker' and active = true
                order by worker_role, name
                """
            ).fetchall()

    stats = {
        "total": int(stats_row["total"] or 0),
        "verified": int(stats_row["verified"] or 0),
        "not_completed": int(stats_row["not_completed"] or 0),
        "rejected": int(stats_row["rejected"] or 0),
        "extended": int(stats_row["extended"] or 0),
    }
    return {
        "stats": stats,
        "yes_count": int(stats_row["yes_count"] or 0),
        "no_count": int(stats_row["no_count"] or 0),
        "extend_count": int(stats_row["extend_count"] or 0),
        "pending_response_count": int(stats_row["pending_response_count"] or 0),
        "pending_manager_count": int(stats_row["pending_manager_count"] or 0),
        "task_metrics": task_metrics[:top_tasks],
        "total_task_groups": int(total_task_groups["group_count"] or 0),
        "workers": workers,
    }


def get_verification_context(run_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            """
            select
                tr.*,
                t.title as task_title,
                t.description as task_description,
                m.id as manager_user_id,
                m.telegram_id as manager_telegram_id,
                m.name as manager_name,
                w.id as worker_user_id,
                w.name as worker_name,
                w.telegram_id as worker_telegram_id
            from task_runs tr
            join tasks t on t.id = tr.task_id
            join users m on m.id = tr.manager_id and m.active = true
            left join users w
              on w.role = 'worker'
             and w.worker_role = tr.worker_role
             and w.active = true
            where tr.id = %s
            """,
            (run_id,),
        ).fetchone()
    return row


def verify_task_run(run_id: str) -> dict[str, Any]:
    verified_at = _now_iso()
    with _connect() as conn:
        run = conn.execute(
            "select * from task_runs where id = %s",
            (run_id,),
        ).fetchone()
        if not run:
            raise ValueError("Task run not found.")

        was_already_finalized = run.get("status") in {
            "manager_verified",
            "manager_rejected",
        }
        run = conn.execute(
            """
            update task_runs
            set status = 'manager_verified',
                manager_status = 'verified',
                verified_at = %s
            where id = %s
            returning *
            """,
            (verified_at, run_id),
        ).fetchone()

        worker = conn.execute(
            """
            select * from users
            where role = 'worker' and worker_role = %s and active = true
            limit 1
            """,
            (run["worker_role"],),
        ).fetchone()

        task = conn.execute(
            "select * from tasks where id = %s",
            (run["task_id"],),
        ).fetchone()

        updated_worker = worker
        if worker and not was_already_finalized:
            updated_worker = conn.execute(
                """
                update users
                set points = points + 1
                where id = %s and role = 'worker' and active = true
                returning *
                """,
                (worker["id"],),
            ).fetchone()

        dependent_tasks: list[dict[str, Any]] = []
        if not was_already_finalized:
            dependent_tasks = conn.execute(
                """
                select *
                from tasks
                where active = true
                  and recurrence = 'after_task'
                  and depends_on_task_id = %s
                order by created_at
                """,
                (run["task_id"],),
            ).fetchall()

    return {
        "run": run,
        "task": task,
        "worker": worker,
        "updated_worker": updated_worker,
        "dependent_tasks": dependent_tasks,
        "was_already_finalized": was_already_finalized,
    }


def reject_task_run(run_id: str) -> dict[str, Any]:
    verified_at = _now_iso()
    with _connect() as conn:
        run = conn.execute(
            "select * from task_runs where id = %s",
            (run_id,),
        ).fetchone()
        if not run:
            raise ValueError("Task run not found.")

        was_already_finalized = run.get("status") in {
            "manager_verified",
            "manager_rejected",
        }
        run = conn.execute(
            """
            update task_runs
            set status = 'manager_rejected',
                manager_status = 'rejected',
                verified_at = %s
            where id = %s
            returning *
            """,
            (verified_at, run_id),
        ).fetchone()

        worker = conn.execute(
            """
            select * from users
            where role = 'worker' and worker_role = %s and active = true
            limit 1
            """,
            (run["worker_role"],),
        ).fetchone()

        task = conn.execute(
            "select * from tasks where id = %s",
            (run["task_id"],),
        ).fetchone()

        updated_worker = worker
        if worker and not (task and task.get("no_penalty")) and not was_already_finalized:
            updated_worker = conn.execute(
                """
                update users
                set points = points - 2
                where id = %s and role = 'worker' and active = true
                returning *
                """,
                (worker["id"],),
            ).fetchone()

    return {
        "run": run,
        "task": task,
        "worker": worker,
        "updated_worker": updated_worker,
        "was_already_finalized": was_already_finalized,
    }


def create_task_run_with_delivery_context(
    task: dict[str, Any],
    scheduled_for: str | None = None,
) -> dict[str, Any] | None:
    if not task or not task.get("active", True):
        return None

    scheduled_value = scheduled_for or _now_iso()
    with _connect() as conn:
        settings_row = conn.execute(
            "select test_mode, test_telegram_id from app_settings where id = true"
        ).fetchone()
        settings = {
            "test_mode": bool(settings_row["test_mode"]) if settings_row else False,
            "test_telegram_id": settings_row["test_telegram_id"] if settings_row else None,
        }

        active_task = conn.execute(
            "select * from tasks where id = %s and active = true",
            (task["id"],),
        ).fetchone()
        if not active_task:
            return None

        worker = conn.execute(
            """
            select * from users
            where role = 'worker' and worker_role = %s and active = true
            limit 1
            """,
            (active_task["worker_role"],),
        ).fetchone()

        if not worker and not settings.get("test_mode"):
            return None

        run = conn.execute(
            """
            insert into task_runs (
                id, task_id, worker_role, manager_id, scheduled_for, status,
                worker_response, reason, worker_note, manager_status,
                created_at, completed_at, verified_at
            )
            values (%s, %s, %s, %s, %s, 'sent_to_worker', null, null, null, 'pending', %s, null, null)
            returning *
            """,
            (
                _new_id("r"),
                active_task["id"],
                active_task["worker_role"],
                active_task["manager_id"],
                scheduled_value,
                _now_iso(),
            ),
        ).fetchone()

        chat_id = (
            settings.get("test_telegram_id")
            if settings.get("test_mode")
            else worker["telegram_id"] if worker else None
        )

    return {
        "run": run,
        "task": active_task,
        "worker": worker,
        "chat_id": chat_id,
        "settings": settings,
    }


def get_run_delivery_context(run_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        settings_row = conn.execute(
            "select test_mode, test_telegram_id from app_settings where id = true"
        ).fetchone()
        settings = {
            "test_mode": bool(settings_row["test_mode"]) if settings_row else False,
            "test_telegram_id": settings_row["test_telegram_id"] if settings_row else None,
        }

        row = conn.execute(
            """
            select
                tr.*,
                t.title as task_title,
                t.description as task_description,
                w.telegram_id as worker_telegram_id
            from task_runs tr
            join tasks t on t.id = tr.task_id
            left join users w
              on w.role = 'worker'
             and w.worker_role = tr.worker_role
             and w.active = true
            where tr.id = %s
            """,
            (run_id,),
        ).fetchone()
        if not row:
            return None

        if not row.get("worker_telegram_id") and not settings.get("test_mode"):
            return None

        chat_id = (
            settings.get("test_telegram_id")
            if settings.get("test_mode")
            else row.get("worker_telegram_id")
        )

    return {
        "run": row,
        "task_title": row["task_title"],
        "task_description": row["task_description"],
        "chat_id": chat_id,
        "settings": settings,
    }


def reset_all() -> None:
    with _connect() as conn:
        conn.execute("delete from task_runs")
        conn.execute("delete from tasks")
        conn.execute("delete from firings")
        conn.execute("delete from users")
        conn.execute("update roles set manager_id = null")
        conn.execute(
            """
            update app_settings
            set test_mode = false,
                test_telegram_id = null
            where id = true
            """
        )
