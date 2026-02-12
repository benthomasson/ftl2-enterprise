# CLAUDE.md — ftl2-enterprise

## What This Is

A database-backed multi-loop reconciler for FTL2. Evolves ftl2-ai-loop from a single in-memory reconcile loop into a persistent automation platform. All loop state is stored in SQLite so loops survive process restarts, browser disconnects, and crashes. Supports multiple concurrent loops with full audit trails.

## Architecture

```
Loop worker → writes state → SQLite (WAL mode)
TUI/Dashboard → reads state → SQLite (WAL mode)

Loops run independently of any UI connection.
The dashboard is a detachable view, like tmux.
```

## Core Components

| File | Purpose |
|------|---------|
| `__init__.py` | CLI entry point — subcommands: `init-db`, `run`, `status`, `history` |
| `schema.py` | SQLAlchemy Core table definitions — all 8 tables as `Table` objects |
| `db.py` | `create_db()` — creates engine with WAL mode and foreign keys enabled |
| `store.py` | Data access layer — insert/query helpers for all tables |
| `worker.py` | Loop worker — wraps ftl2-ai-loop's `reconcile()` with DB writes |

### Key Functions

| Function | Location | Purpose |
|----------|----------|---------|
| `cli()` | `__init__.py` | Argparse with subcommands, dispatches to worker or query commands |
| `create_db(path)` | `db.py` | Creates SQLite engine with WAL mode, runs `metadata.create_all()` |
| `create_loop(engine, ...)` | `store.py` | Insert a new loop row, returns loop ID |
| `insert_iteration(engine, ...)` | `store.py` | Record an observe → decide → execute cycle |
| `insert_action(engine, ...)` | `store.py` | Record a module execution with rc/stdout/stderr |
| `insert_prompt(engine, ...)` | `store.py` | Record a pending human-in-the-loop prompt |
| `list_loops(engine, status)` | `store.py` | Query loops, optionally filtered by status |
| `get_iterations(engine, loop_id)` | `store.py` | Get all iterations for a loop |
| `get_actions_for_loop(engine, loop_id)` | `store.py` | Get all actions across all iterations |
| `run_loop(...)` | `worker.py` | Async entry point — creates loop, calls reconcile(), writes history to DB |
| `run(...)` | `worker.py` | Sync wrapper — calls `asyncio.run(run_loop(...))` |

## Database Schema

Eight tables, all defined in `schema.py`:

```
loops (top-level)
 ├── increments (incremental mode steps)
 ├── iterations (each observe → decide → execute cycle)
 │    ├── actions (module executions on hosts)
 │    └── rule_results (rule condition evaluations)
 ├── hosts (managed inventory)
 ├── prompts (human-in-the-loop interactions)
 └── resources (state file entries)
```

### Design Decisions

- **SQLAlchemy Core** (not ORM) — append-only write pattern and dashboard reads are simpler with Core. No session management overhead.
- **SQLite with WAL** — zero infrastructure, concurrent readers with single writer, built into Python.
- **JSON text columns** — `observations`, `params`, `facts`, `groups`, `options`, `data` store JSON as text. Avoids schema explosion for variable/nested data.
- **`server_default` for timestamps** — uses SQLite's `datetime('now')` for automatic timestamps.

## Configuration

No environment variables or config files. The database path is the only configuration, passed via `--db` flag (defaults to `loops.db`).

## Running

```bash
# Via uvx from GitHub (no install)
uvx --from "git+https://github.com/benthomasson/ftl2-enterprise" \
    ftl2-enterprise init-db

# Local development
pip install -e .
ftl2-enterprise init-db

# Run a loop
ftl2-enterprise run "Install nginx" -i inventory.yml

# Query results
ftl2-enterprise status --all
ftl2-enterprise history 1 --actions
```

## Key Files

```
ftl2_enterprise/
├── __init__.py     # CLI entry point with subcommands
├── db.py           # Database creation with WAL mode
├── schema.py       # SQLAlchemy Core table definitions
├── store.py        # Data access layer (insert/query helpers)
└── worker.py       # Loop worker (wraps ftl2-ai-loop with DB writes)
pyproject.toml      # Hatchling build, Python >=3.13, Apache-2.0
```
