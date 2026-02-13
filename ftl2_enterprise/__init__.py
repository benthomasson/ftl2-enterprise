import argparse
import sys

from .db import create_db


def cli():
    parser = argparse.ArgumentParser(
        description="ftl2-enterprise — database-backed multi-loop reconciler"
    )
    parser.add_argument("--db", default="loops.db",
                        help="SQLite database path (default: loops.db)")
    subparsers = parser.add_subparsers(dest="command")

    # --- init-db ---
    subparsers.add_parser("init-db", help="Create database tables and exit")

    # --- run ---
    run_parser = subparsers.add_parser("run", help="Run a reconcile loop")
    run_parser.add_argument("desired_state", help="Desired state description")
    run_parser.add_argument("-i", "--inventory", help="Inventory file path")
    run_parser.add_argument("--mode", choices=["single", "incremental", "continuous"],
                            default="single", help="Loop mode (default: single)")
    run_parser.add_argument("--max-iterations", type=int, default=10,
                            help="Max iterations per reconcile (default: 10)")
    run_parser.add_argument("--interval", type=int, default=60,
                            help="Delay between runs in continuous/incremental mode (default: 60)")
    run_parser.add_argument("--dry-run", action="store_true",
                            help="Show actions without executing")
    run_parser.add_argument("--quiet", action="store_true",
                            help="Suppress verbose output")
    run_parser.add_argument("--state-file", help="FTL2 state file path")
    run_parser.add_argument("--policy", help="Policy file path")
    run_parser.add_argument("--environment", default="", help="Environment name")
    run_parser.add_argument("--rules-dir", default="rules", help="Rules directory")
    run_parser.add_argument("--plan-file", help="Saved plan file (incremental mode)")

    # --- worker ---
    worker_parser = subparsers.add_parser("worker", help="Run the long-running worker daemon")
    worker_parser.add_argument("--poll-interval", type=float, default=5.0,
                                help="Seconds between poll cycles (default: 5.0)")

    # --- submit ---
    submit_parser = subparsers.add_parser("submit", help="Submit a new loop for the worker")
    submit_parser.add_argument("desired_state", help="Desired state description")
    submit_parser.add_argument("-i", "--inventory", help="Inventory file path")
    submit_parser.add_argument("--mode", choices=["single", "incremental", "continuous"],
                                default="single", help="Loop mode (default: single)")
    submit_parser.add_argument("--interval", type=int, default=60,
                                help="Delay between runs in continuous/incremental mode (default: 60)")

    # --- respond ---
    respond_parser = subparsers.add_parser("respond", help="Respond to a pending prompt")
    respond_parser.add_argument("prompt_id", type=int, help="Prompt ID")
    respond_parser.add_argument("response", help="Response text")

    # --- tui ---
    subparsers.add_parser("tui", help="Launch the dashboard TUI")

    # --- status ---
    status_parser = subparsers.add_parser("status", help="Show loop status")
    status_parser.add_argument("--all", action="store_true",
                               help="Show all loops (default: running and pending)")

    # --- history ---
    history_parser = subparsers.add_parser("history", help="Show loop history")
    history_parser.add_argument("loop_id", type=int, help="Loop ID")
    history_parser.add_argument("--actions", action="store_true",
                                help="Include action details")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    if args.command == "init-db":
        create_db(args.db)
        print(f"Database initialized: {args.db}")
        return

    if args.command == "run":
        from .worker import run
        run(
            db_path=args.db,
            desired_state=args.desired_state,
            inventory=args.inventory,
            mode=args.mode,
            max_iterations=args.max_iterations,
            interval=args.interval,
            dry_run=args.dry_run,
            quiet=args.quiet,
            state_file=args.state_file,
            policy=args.policy,
            environment=args.environment,
            rules_dir=args.rules_dir,
            plan_file=args.plan_file,
        )
        return

    if args.command == "worker":
        from .worker import worker
        worker(db_path=args.db, poll_interval=args.poll_interval)
        return

    if args.command == "submit":
        _cmd_submit(args)
        return

    if args.command == "respond":
        _cmd_respond(args)
        return

    if args.command == "tui":
        from .tui import run_tui
        run_tui(db_path=args.db)
        return

    if args.command == "status":
        _cmd_status(args)
        return

    if args.command == "history":
        _cmd_history(args)
        return


def _cmd_status(args):
    from . import store

    engine = create_db(args.db)
    if args.all:
        all_loops = store.list_loops(engine)
    else:
        all_loops = (store.list_loops(engine, status="running")
                     + store.list_loops(engine, status="pending"))

    if not all_loops:
        print("No loops found.")
        return

    # Header
    print(f"{'ID':>4}  {'Status':<10}  {'Mode':<12}  {'Created':<20}  {'Name'}")
    print(f"{'--':>4}  {'------':<10}  {'----':<12}  {'-------':<20}  {'----'}")

    for loop in all_loops:
        created = (loop.get("created_at") or "")[:19]
        print(f"{loop['id']:>4}  {loop['status']:<10}  {loop['mode']:<12}  "
              f"{created:<20}  {loop['name']}")


def _cmd_history(args):
    from . import store

    engine = create_db(args.db)
    loop = store.get_loop(engine, args.loop_id)

    if not loop:
        print(f"Loop #{args.loop_id} not found.", file=sys.stderr)
        sys.exit(1)

    print(f"Loop #{loop['id']}: {loop['name']}")
    print(f"Status: {loop['status']}  Mode: {loop['mode']}")
    if loop.get("desired_state"):
        ds = loop["desired_state"]
        if len(ds) > 100:
            ds = ds[:100] + "..."
        print(f"Desired state: {ds}")
    print()

    iters = store.get_iterations(engine, args.loop_id)
    if not iters:
        print("No iterations recorded.")
        return

    for it in iters:
        converged = "yes" if it.get("converged") else "no"
        print(f"  Iteration {it['n']}: converged={converged}")
        if it.get("reasoning"):
            reasoning = it["reasoning"]
            if len(reasoning) > 120:
                reasoning = reasoning[:120] + "..."
            print(f"    Reasoning: {reasoning}")

        if args.actions:
            actions_list = store.get_actions_for_iteration(engine, it["id"])
            for action in actions_list:
                rc = action.get("rc", "?")
                status = action.get("status", "?")
                host = ""
                module = action.get("module", "?")
                print(f"    [{status}] {module} rc={rc}{host}")
                if action.get("stdout"):
                    for line in action["stdout"].splitlines()[:3]:
                        print(f"      | {line}")

    total = store.count_actions(engine, args.loop_id)
    print(f"\nTotal: {len(iters)} iterations, {total} actions")


def _cmd_submit(args):
    from . import store

    engine = create_db(args.db)
    loop_id = store.create_loop(
        engine,
        name=args.desired_state[:80],
        desired_state=args.desired_state,
        mode=args.mode,
        inventory=args.inventory,
        interval=args.interval if args.mode != "single" else None,
    )
    print(f"Loop #{loop_id} submitted (status: pending)")
    print(f"The worker will pick it up on its next poll cycle.")


def _cmd_respond(args):
    from . import store

    engine = create_db(args.db)
    store.record_response(engine, args.prompt_id, args.response)
    print(f"Response recorded for prompt #{args.prompt_id}")
