"""Loop worker for ftl2-enterprise.

Implements the full worker lifecycle from the loop-worker-design entry:
  1. Startup: connect to DB, pick up running/pending loops
  2. For each loop: set up FTL2 automation context, run observe→decide→execute
  3. Write to DB after each iteration (atomic commit boundary)
  4. Handle prompts via DB (write prompt, pause, pick up response)
  5. Poll for new/paused/cancelled loops between iterations
  6. Crash recovery: resume from last committed iteration
"""

import asyncio
import signal
import sys
import traceback

from .db import create_db
from . import store


async def _run_iteration(ftl, engine, loop_id, iteration_n, desired_state,
                         observers, rules, history, max_iterations, dry_run):
    """Run one observe → decide → execute cycle, writing results to DB.

    Returns (converged: bool, should_continue: bool, prompt_pending: bool)
    """
    from ftl2_ai_loop import observe, decide, execute

    print(f"  === Loop #{loop_id} — Iteration {iteration_n + 1} ===")

    # ========== OBSERVE ==========
    print("  Observing...")
    current_state = await observe(ftl, observers)

    # Include state file contents
    if hasattr(ftl, 'state') and ftl.state:
        try:
            state_contents = {}
            resources = ftl.state.resources()
            if resources:
                state_contents["resources"] = resources
            hosts = ftl.state.hosts()
            if hosts:
                state_contents["hosts"] = {
                    name: ftl.state.get_host(name) for name in hosts
                }
            if state_contents:
                current_state["_state_file"] = state_contents
        except Exception:
            traceback.print_exc()

    # ========== DECIDE ==========
    print("  Asking AI...")
    decision = await decide(
        current_state, desired_state, rules, history,
        iteration=iteration_n, max_iterations=max_iterations,
    )

    reasoning = decision.get("reasoning", "")
    if reasoning:
        print(f"    Reasoning: {reasoning[:200]}")

    # Handle convergence
    if decision.get("converged"):
        print(f"  Converged after {iteration_n + 1} iteration(s).")
        store.insert_iteration(
            engine, loop_id=loop_id, n=iteration_n,
            converged=True, reasoning=reasoning,
            observations=current_state,
        )
        history.append({
            "iteration": iteration_n, "reasoning": reasoning,
            "converged": True, "actions": [], "results": [],
        })
        return True, False, False

    # Handle prompt request
    ask_data = decision.get("ask")
    if ask_data and ask_data.get("question"):
        question = ask_data["question"]
        options = ask_data.get("options")
        print(f"  AI asks: {question}")
        iter_id = store.insert_iteration(
            engine, loop_id=loop_id, n=iteration_n,
            converged=False, reasoning=reasoning,
            observations=current_state,
        )
        store.insert_prompt(
            engine, loop_id=loop_id, iteration_id=iter_id,
            prompt_text=question, options=options,
        )
        history.append({
            "iteration": iteration_n, "reasoning": reasoning,
            "asked": question, "actions": [], "results": [],
        })
        return False, False, True  # prompt pending — pause this loop

    # ========== EXECUTE ==========
    actions_list = decision.get("actions", [])
    extra_observers = decision.get("observe", [])

    if not actions_list:
        store.insert_iteration(
            engine, loop_id=loop_id, n=iteration_n,
            converged=False, reasoning=reasoning,
            observations=current_state,
        )
        history.append({
            "iteration": iteration_n, "reasoning": reasoning,
            "actions": [], "results": [],
            "observations_requested": len(extra_observers),
        })
        print("  No actions decided.")
        return False, True, False

    print(f"  Executing {len(actions_list)} action(s)...")
    results = await execute(ftl, actions_list, dry_run)

    # Write iteration + actions to DB
    iter_id = store.insert_iteration(
        engine, loop_id=loop_id, n=iteration_n,
        converged=False, reasoning=reasoning,
        observations=current_state,
    )
    for i, action in enumerate(actions_list):
        result = results[i] if i < len(results) else {}
        result_data = result.get("result", {})
        store.insert_action(
            engine, iteration_id=iter_id,
            module=action.get("module", "unknown"),
            params=action.get("params"),
            host=action.get("host"),
            rc=result_data.get("rc"),
            stdout=result_data.get("stdout"),
            stderr=result_data.get("stderr"),
            changed=result_data.get("changed"),
            status="failed" if result_data.get("failed") or result_data.get("error") else "completed",
        )

    # Handle state operations
    state_ops = decision.get("state_ops", [])
    if state_ops and not dry_run:
        for op in state_ops:
            op_type = op.get("op")
            name = op.get("name", "")
            try:
                if op_type == "add_resource":
                    if hasattr(ftl, 'state') and ftl.state:
                        ftl.state.add_resource(name, op.get("data", {}))
                    print(f"    State: added resource {name}")
                elif op_type == "add_host":
                    ftl.add_host(
                        hostname=name,
                        ansible_host=op.get("ansible_host"),
                        ansible_user=op.get("ansible_user", "root"),
                        groups=op.get("groups"),
                    )
                    print(f"    Host added: {name} ({op.get('ansible_host', name)})")
                elif op_type == "remove":
                    if hasattr(ftl, 'state') and ftl.state:
                        ftl.state.remove(name)
                    print(f"    State: removed {name}")
            except Exception as e:
                print(f"    State op failed: {e}")

    history.append({
        "iteration": iteration_n, "reasoning": reasoning,
        "actions": actions_list, "results": results,
    })

    return False, True, False


async def run_worker(db_path: str, poll_interval: float = 5.0):
    """Long-running worker daemon.

    Lifecycle:
      1. Pick up pending and running loops from DB
      2. For each loop, run iterations with DB writes
      3. Poll for new loops between iterations
      4. Handle prompts via DB
    """
    from ftl2 import automation
    from ftl2_ai_loop import load_rules

    engine = create_db(db_path)
    running = True

    def handle_signal(sig, frame):
        nonlocal running
        print("\nWorker shutting down...")
        running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    print(f"Worker started (db: {db_path}, poll: {poll_interval}s)")

    while running:
        # Pick up pending loops
        pending = store.list_loops(engine, status="pending")
        for loop_data in pending:
            if not running:
                break

            loop_id = loop_data["id"]
            desired_state = loop_data.get("desired_state", "")
            inventory = loop_data.get("inventory")
            mode = loop_data.get("mode", "single")
            interval = loop_data.get("interval") or 60
            max_iterations = 10

            print(f"\nStarting loop #{loop_id}: {desired_state[:80]}")
            store.start_loop(engine, loop_id)

            # Rebuild history from DB (for crash recovery)
            history = store.get_history_for_ai(engine, loop_id)
            resume_from = store.get_last_iteration_number(engine, loop_id) + 1

            if resume_from > 0:
                print(f"  Resuming from iteration {resume_from} ({len(history)} iterations in DB)")

            automation_kwargs = {"inventory": inventory, "quiet": True}
            if loop_data.get("groups"):
                pass  # groups are parsed from inventory

            converged = False
            prompt = False
            try:
                async with automation(**automation_kwargs) as ftl:
                    rules = load_rules("rules")

                    for i in range(resume_from, max_iterations):
                        if not running:
                            break

                        conv, cont, prompt = await _run_iteration(
                            ftl, engine, loop_id, i, desired_state,
                            observers=[], rules=rules, history=history,
                            max_iterations=max_iterations, dry_run=False,
                        )

                        if conv:
                            converged = True
                            break
                        if prompt:
                            print(f"  Loop #{loop_id} paused (waiting for prompt response)")
                            store.pause_loop(engine, loop_id)
                            break
                        if not cont:
                            break

                        await asyncio.sleep(2)

                    if not converged and not prompt:
                        print(f"  Loop #{loop_id} did not converge after {max_iterations} iterations")

            except Exception as e:
                print(f"  Loop #{loop_id} error: {e}", file=sys.stderr)
                traceback.print_exc()
            finally:
                if not prompt:
                    store.complete_loop(engine, loop_id, converged=converged)
                    total_actions = store.count_actions(engine, loop_id)
                    iters = store.get_iterations(engine, loop_id)
                    print(f"  Loop #{loop_id} finished: converged={converged}, "
                          f"iterations={len(iters)}, actions={total_actions}")

        # Check for paused loops with answered prompts
        paused = store.list_loops(engine, status="paused")
        for loop_data in paused:
            if not running:
                break
            loop_id = loop_data["id"]
            pending_prompts = store.get_pending_prompts(engine, loop_id)
            if not pending_prompts:
                # All prompts answered — resume the loop
                print(f"\nResuming loop #{loop_id} (prompt answered)")
                store.start_loop(engine, loop_id)
                # It will be picked up as running on next tick

        # Poll interval
        if running:
            await asyncio.sleep(poll_interval)

    print("Worker stopped.")


# --- Legacy one-shot mode (kept for `ftl2-enterprise run`) ---


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
    """Run a single reconcile loop inline (one-shot mode)."""
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
            converged = True

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
    """Synchronous entry point for `ftl2-enterprise run`."""
    asyncio.run(run_loop(db_path=db_path, desired_state=desired_state, **kwargs))


def worker(*, db_path: str, poll_interval: float = 5.0):
    """Synchronous entry point for `ftl2-enterprise worker`."""
    asyncio.run(run_worker(db_path=db_path, poll_interval=poll_interval))
