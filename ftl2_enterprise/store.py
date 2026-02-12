"""Data access layer for ftl2-enterprise.

Thin helpers over SQLAlchemy Core for the common write and read operations.
All JSON fields are serialized/deserialized automatically.
"""

import json
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.engine import Engine

from .schema import loops, iterations, actions, prompts, hosts, increments


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(obj):
    if obj is None:
        return None
    return json.dumps(obj)


# --- Writes ---


def create_loop(engine: Engine, *, name: str, desired_state: str,
                mode: str = "single", inventory: str | None = None,
                groups: list | None = None, interval: float | None = None) -> int:
    """Create a new loop and return its ID."""
    with engine.begin() as conn:
        result = conn.execute(
            loops.insert().values(
                name=name,
                desired_state=desired_state,
                mode=mode,
                inventory=inventory,
                groups=_json(groups),
                interval=interval,
                status="pending",
                created_at=_now(),
            )
        )
        return result.inserted_primary_key[0]


def start_loop(engine: Engine, loop_id: int):
    """Mark a loop as running."""
    with engine.begin() as conn:
        conn.execute(
            loops.update().where(loops.c.id == loop_id).values(
                status="running",
                started_at=_now(),
            )
        )


def complete_loop(engine: Engine, loop_id: int, *, converged: bool):
    """Mark a loop as completed or failed."""
    with engine.begin() as conn:
        conn.execute(
            loops.update().where(loops.c.id == loop_id).values(
                status="completed" if converged else "failed",
                completed_at=_now(),
            )
        )


def insert_iteration(engine: Engine, *, loop_id: int, n: int,
                      increment_id: int | None = None,
                      converged: bool | None = None,
                      reasoning: str | None = None,
                      observations: dict | None = None) -> int:
    """Insert an iteration and return its ID."""
    with engine.begin() as conn:
        result = conn.execute(
            iterations.insert().values(
                loop_id=loop_id,
                increment_id=increment_id,
                n=n,
                phase="completed",
                converged=1 if converged else (0 if converged is not None else None),
                reasoning=reasoning,
                observations=_json(observations),
                created_at=_now(),
                completed_at=_now(),
            )
        )
        return result.inserted_primary_key[0]


def insert_action(engine: Engine, *, iteration_id: int, module: str,
                   params: dict | None = None, host: str | None = None,
                   host_id: int | None = None,
                   rc: int | None = None, stdout: str | None = None,
                   stderr: str | None = None, changed: bool | None = None,
                   status: str = "completed") -> int:
    """Insert an action result and return its ID."""
    with engine.begin() as conn:
        result = conn.execute(
            actions.insert().values(
                iteration_id=iteration_id,
                host_id=host_id,
                module=module,
                params=_json(params),
                status=status,
                rc=rc,
                stdout=stdout,
                stderr=stderr,
                changed=1 if changed else (0 if changed is not None else None),
                completed_at=_now(),
            )
        )
        return result.inserted_primary_key[0]


def insert_prompt(engine: Engine, *, loop_id: int, iteration_id: int | None = None,
                  prompt_text: str, options: list | None = None) -> int:
    """Insert a pending prompt and return its ID."""
    with engine.begin() as conn:
        result = conn.execute(
            prompts.insert().values(
                loop_id=loop_id,
                iteration_id=iteration_id,
                prompt_text=prompt_text,
                options=_json(options),
                status="pending",
                created_at=_now(),
            )
        )
        return result.inserted_primary_key[0]


def record_response(engine: Engine, prompt_id: int, response: str):
    """Record a user's response to a prompt."""
    with engine.begin() as conn:
        conn.execute(
            prompts.update().where(prompts.c.id == prompt_id).values(
                response=response,
                status="answered",
                answered_at=_now(),
            )
        )


def insert_increment(engine: Engine, *, loop_id: int, n: int,
                      desired_state: str, is_fix: bool = False) -> int:
    """Insert an increment step and return its ID."""
    with engine.begin() as conn:
        result = conn.execute(
            increments.insert().values(
                loop_id=loop_id,
                n=n,
                desired_state=desired_state,
                status="pending",
                is_fix=1 if is_fix else 0,
                created_at=_now(),
            )
        )
        return result.inserted_primary_key[0]


def complete_increment(engine: Engine, increment_id: int, *, converged: bool):
    """Mark an increment as converged or failed."""
    with engine.begin() as conn:
        conn.execute(
            increments.update().where(increments.c.id == increment_id).values(
                status="converged" if converged else "failed",
                completed_at=_now(),
            )
        )


# --- Reads ---


def list_loops(engine: Engine, status: str | None = None) -> list[dict]:
    """List all loops, optionally filtered by status."""
    with engine.connect() as conn:
        query = select(loops).order_by(loops.c.id.desc())
        if status:
            query = query.where(loops.c.status == status)
        rows = conn.execute(query).fetchall()
        return [dict(row._mapping) for row in rows]


def get_loop(engine: Engine, loop_id: int) -> dict | None:
    """Get a single loop by ID."""
    with engine.connect() as conn:
        row = conn.execute(
            select(loops).where(loops.c.id == loop_id)
        ).fetchone()
        return dict(row._mapping) if row else None


def get_iterations(engine: Engine, loop_id: int) -> list[dict]:
    """Get all iterations for a loop, ordered by sequence number."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(iterations)
            .where(iterations.c.loop_id == loop_id)
            .order_by(iterations.c.n)
        ).fetchall()
        return [dict(row._mapping) for row in rows]


def get_actions_for_iteration(engine: Engine, iteration_id: int) -> list[dict]:
    """Get all actions for an iteration."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(actions)
            .where(actions.c.iteration_id == iteration_id)
            .order_by(actions.c.id)
        ).fetchall()
        return [dict(row._mapping) for row in rows]


def get_actions_for_loop(engine: Engine, loop_id: int) -> list[dict]:
    """Get all actions across all iterations for a loop."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(actions)
            .join(iterations, actions.c.iteration_id == iterations.c.id)
            .where(iterations.c.loop_id == loop_id)
            .order_by(iterations.c.n, actions.c.id)
        ).fetchall()
        return [dict(row._mapping) for row in rows]


def get_pending_prompts(engine: Engine, loop_id: int | None = None) -> list[dict]:
    """Get pending prompts, optionally filtered by loop."""
    with engine.connect() as conn:
        query = select(prompts).where(prompts.c.status == "pending")
        if loop_id is not None:
            query = query.where(prompts.c.loop_id == loop_id)
        rows = conn.execute(query.order_by(prompts.c.id)).fetchall()
        return [dict(row._mapping) for row in rows]


def count_actions(engine: Engine, loop_id: int) -> int:
    """Count total actions for a loop."""
    with engine.connect() as conn:
        row = conn.execute(
            select(func.count(actions.c.id))
            .join(iterations, actions.c.iteration_id == iterations.c.id)
            .where(iterations.c.loop_id == loop_id)
        ).fetchone()
        return row[0] if row else 0
