import uuid
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from config import ADMIN_TELEGRAM_ID, DATABASE_URL

DEFAULT_ROLES = ["Driver", "Cook", "Cleaner", "Security"]


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _is_env_admin(telegram_id: int) -> bool:
    return bool(ADMIN_TELEGRAM_ID and telegram_id == ADMIN_TELEGRAM_ID)


def _admin_user() -> dict[str, Any]:
    return {
        "id": "env_admin",
        "telegram_id": ADMIN_TELEGRAM_ID,
        "name": "Admin",
        "role": "admin",
        "worker_role": None,
        "manager_password": None,
        "active": True,
        "created_at": None,
    }


def _connect():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is required. Set it to your Supabase Postgres connection string."
        )
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        sslmode="require",
        prepare_threshold=None,
    )


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
            role text not null check (role in ('admin', 'manager', 'worker')),
            worker_role text,
            manager_password text,
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
            time text not null,
            scheduled_date text,
            recurrence text not null default 'daily',
            weekday integer,
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

        alter table tasks add column if not exists scheduled_date text;
        alter table task_runs add column if not exists worker_note text;

        create table if not exists firings (
            id text primary key,
            worker_id text not null,
            worker_name text,
            worker_role text,
            worker_telegram_id bigint,
            manager_id text not null,
            reason text not null,
            created_at text not null
        );

        create unique index if not exists users_active_manager_password_idx
            on users(manager_password)
            where role = 'manager' and active = true and manager_password is not null;
        create unique index if not exists users_active_worker_role_idx
            on users(worker_role)
            where role = 'worker' and active = true and worker_role is not null;
        create index if not exists tasks_active_manager_idx on tasks(manager_id, active);
        create index if not exists task_runs_report_idx on task_runs(worker_role, created_at);

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


def get_manager_by_password(password: str) -> dict[str, Any] | None:
    password = password.strip()
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


def update_manager_password(manager_id: str, password: str) -> dict[str, Any]:
    password = password.strip()
    if not password:
        raise ValueError("Manager password is required.")

    with _connect() as conn:
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

        manager = conn.execute(
            """
            update users
            set manager_password = %s
            where id = %s and role = 'manager' and active = true
            returning *
            """,
            (password, manager_id),
        ).fetchone()
        if not manager:
            raise ValueError("Manager not found.")
        return manager


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
            manager_password = (manager_password or "").strip()
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
                id, telegram_id, name, role, worker_role, manager_password, active, created_at
            )
            values (%s, %s, %s, %s, %s, %s, true, %s)
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

        task = conn.execute(
            """
            insert into tasks (
                id, title, description, worker_role, manager_id, time, scheduled_date,
                recurrence, weekday, active, created_at
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s)
            returning *
            """,
            (
                _new_id("t"),
                title.strip(),
                description.strip(),
                worker_role,
                manager_id,
                time_hhmm,
                scheduled_date,
                recurrence,
                weekday,
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
                manager_id, reason, created_at
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s)
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
            set active = false,
                fired_at = %s,
                fired_by_manager_id = %s,
                fired_reason = %s
            where id = %s
            """,
            (fired_at, manager_id, reason.strip(), worker_id),
        )
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


def list_tasks_for_manager(manager_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        return conn.execute(
            """
            select
                t.*,
                coalesce(u.name, 'Unassigned') as worker_name,
                u.telegram_id as worker_telegram_id
            from tasks t
            left join users u
              on u.role = 'worker'
             and u.worker_role = t.worker_role
             and u.active = true
            where t.manager_id = %s and t.active = true
            order by t.created_at
            """,
            (manager_id,),
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
        "time",
        "scheduled_date",
        "recurrence",
        "weekday",
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
