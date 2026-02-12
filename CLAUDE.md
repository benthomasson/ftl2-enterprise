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
| `__init__.py` | CLI entry point — `cli()` parses args, `--init-db` creates tables |
| `schema.py` | SQLAlchemy Core table definitions — all 8 tables as `Table` objects |
| `db.py` | `create_db()` — creates engine with WAL mode and foreign keys enabled |

### Key Functions

| Function | Location | Purpose |
|----------|----------|---------|
| `cli()` | `__init__.py` | Argparse + DB initialization |
| `create_db(path)` | `db.py` | Creates SQLite engine with WAL mode, runs `metadata.create_all()` |

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
# Initialize the database
ftl2-enterprise --init-db

# With custom DB path
ftl2-enterprise --db /var/lib/ftl2/loops.db --init-db
```

## Key Files

```
ftl2_enterprise/
├── __init__.py     # CLI entry point
├── db.py           # Database creation with WAL mode
└── schema.py       # SQLAlchemy Core table definitions
pyproject.toml      # Hatchling build, Python >=3.13, Apache-2.0
```
