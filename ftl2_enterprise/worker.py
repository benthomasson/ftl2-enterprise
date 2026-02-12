"""Loop worker for ftl2-enterprise.

Wraps ftl2-ai-loop's reconcile() and run_incremental() with database writes.
The reconcile logic is unchanged — this module records everything to SQLite.
"""

import asyncio
import json
import sys

from .db import create_db
from . import store


def _write_history(engine, loop_id, history, increment_id=None):
    """Write a reconcile() result's history list to the database."""
    for entry in history:
        iteration_id = store.insert_iteration(
            engine,
            loop_id=loop_id,
            n=entry.get("iteration", 0),
            increment_id=increment_id,
            converged=entry.get("converged"),
            reasoning=entry.get("reasoning"),
        )

        # Write actions and their results together
        actions_list = entry.get("actions", [])
        results_list = entry.get("results", [])

        for i, action in enumerate(actions_list):
            result = results_list[i] if i < len(results_list) else {}
            result_data = result.get("result", {})

            store.insert_action(
                engine,
                iteration_id=iteration_id,
                module=action.get("module", "unknown"),
                params=action.get("params"),
                host=action.get("host"),
                rc=result_data.get("rc"),
                stdout=result_data.get("stdout"),
                stderr=result_data.get("stderr"),
                changed=result_data.get("changed"),
                status="failed" if result_data.get("failed") else "completed",
            )


async def run_loop(*, db_path: str, desired_state: str,
                   inventory: str | None = None,
                   mode: str = "single",
                   max_iterations: int = 10,
                   interval: int = 60,
                   dry_run: bool = False,
                   quiet: bool = False,
                   state_file: str | None = None,
                   policy: str | None = None,
                   environment: str = "",
                   rules_dir: str = "rules",
                   plan_file: str | None = None):
    """Run a reconcile loop with full DB recording."""

    # Late import so ftl2-ai-loop is only needed when actually running
    from ftl2_ai_loop import reconcile, run_incremental, run_continuous

    engine = create_db(db_path)

    loop_id = store.create_loop(
        engine,
        name=desired_state[:80],
        desired_state=desired_state,
        mode=mode,
        inventory=inventory,
        interval=interval if mode == "continuous" else None,
    )
    print(f"Loop #{loop_id} created ({mode} mode)")

    store.start_loop(engine, loop_id)

    reconcile_kwargs = dict(
        desired_state=desired_state,
        inventory=inventory,
        max_iterations=max_iterations,
        dry_run=dry_run,
        quiet=quiet,
        state_file=state_file,
        policy=policy,
        environment=environment,
        rules_dir=rules_dir,
    )

    converged = False

    try:
        if mode == "single":
            result = await reconcile(**reconcile_kwargs)
            _write_history(engine, loop_id, result.get("history", []))
            converged = result.get("converged", False)

        elif mode == "incremental":
            run_number = [0]

            def notify(**kwargs):
                run_number[0] += 1
                n = run_number[0]
                inc_id = store.insert_increment(
                    engine,
                    loop_id=loop_id,
                    n=n,
                    desired_state=kwargs.get("desired_state", ""),
                    is_fix=False,
                )
                store.complete_increment(
                    engine, inc_id,
                    converged=kwargs.get("converged", False),
                )
                print(f"  Increment #{n}: converged={kwargs.get('converged')}, "
                      f"iterations={kwargs.get('iterations')}, "
                      f"actions={kwargs.get('actions_taken')}")

            await run_incremental(
                reconcile_kwargs=reconcile_kwargs,
                plan_file=plan_file,
                notify=notify,
                delay=interval,
            )
            converged = True  # run_incremental completes all increments

        elif mode == "continuous":
            def notify(**kwargs):
                run_n = kwargs.get("run_number", 0)
                print(f"  Run #{run_n}: converged={kwargs.get('converged')}, "
                      f"iterations={kwargs.get('iterations')}, "
                      f"actions={kwargs.get('actions_taken')}")

            await run_continuous(
                reconcile_kwargs=reconcile_kwargs,
                delay=interval,
                notify=notify,
            )

    except KeyboardInterrupt:
        print(f"\nLoop #{loop_id} interrupted")
        converged = False
    except Exception as e:
        print(f"Loop #{loop_id} error: {e}", file=sys.stderr)
        converged = False
        raise
    finally:
        store.complete_loop(engine, loop_id, converged=converged)
        total_actions = store.count_actions(engine, loop_id)
        iters = store.get_iterations(engine, loop_id)
        print(f"Loop #{loop_id} finished: converged={converged}, "
              f"iterations={len(iters)}, actions={total_actions}")


def run(*, db_path: str, desired_state: str, **kwargs):
    """Synchronous entry point for the CLI."""
    asyncio.run(run_loop(db_path=db_path, desired_state=desired_state, **kwargs))
