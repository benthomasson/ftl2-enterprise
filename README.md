# ftl2-enterprise

Database-backed multi-loop reconciler for [FTL2](https://github.com/benthomasson/ftl2). Moves reconcile loop state from in-memory to SQLite, enabling persistent loops that survive browser disconnects, process restarts, and crashes. Supports multiple concurrent loops with full audit trails.

## Why

[ftl2-ai-loop](https://github.com/benthomasson/ftl2-ai-loop) runs a single reconcile loop with all state in memory. If the process dies — or the browser tab goes idle and textual-serve drops the WebSocket — the loop and its in-progress work are lost. ftl2-enterprise solves this by storing all loop state in a database, making loops persistent and independent of any UI connection.

## Architecture

```
                    ┌─────────────┐
                    │   SQLite    │
                    │   (WAL)     │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────┴─────┐ ┌───┴───┐ ┌─────┴─────┐
        │  Loop 1   │ │Loop 2 │ │  Loop N   │
        │  (web)    │ │(infra)│ │  (...)    │
        └───────────┘ └───────┘ └───────────┘
              │            │            │
              └────────────┼────────────┘
                           │
                    ┌──────┴──────┐
                    │  TUI / Web  │
                    │  Dashboard  │
                    └─────────────┘
```

Loop workers write state to the database. The TUI/dashboard reads it. Loops run independently of any UI — the dashboard is a detachable view, like tmux.

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)

## Quick Start

```bash
# Run directly from GitHub — no install needed
uvx --from "git+https://github.com/benthomasson/ftl2-enterprise" \
    ftl2-enterprise init-db

# Or install locally
pip install -e .
ftl2-enterprise init-db
```

### Run a loop

```bash
# Single reconcile run
ftl2-enterprise run "Install nginx on all web servers" -i inventory.yml

# Incremental mode (plan → execute step by step)
ftl2-enterprise run "Set up a LAMP stack" -i inventory.yml --mode incremental

# Continuous mode (reconcile on a timer)
ftl2-enterprise run "Ensure nginx is running" -i inventory.yml --mode continuous --interval 60
```

### Query the database

```bash
# Show running and pending loops
ftl2-enterprise status

# Show all loops (including completed/failed)
ftl2-enterprise status --all

# Show iteration history for a loop
ftl2-enterprise history 1

# Show history with full action details (module, rc, stdout)
ftl2-enterprise history 1 --actions
```

## Database

SQLite with WAL mode. Eight tables:

| Table | Purpose |
|-------|---------|
| `loops` | Top-level loop instances (config, status, mode) |
| `increments` | Planned steps for incremental mode |
| `iterations` | Each observe → decide → execute cycle |
| `hosts` | Managed hosts with facts and status |
| `actions` | Module executions with full stdout/stderr/rc |
| `prompts` | Human-in-the-loop questions and responses |
| `resources` | Managed resources (state file entries) |
| `rule_results` | Rule condition evaluations and AI approvals |

Data access uses SQLAlchemy Core (not ORM) for direct SQL control on the hot path.

## CLI

```
ftl2-enterprise [--db PATH] <command>
```

| Command | Description |
|---------|-------------|
| `init-db` | Create database tables |
| `run <desired_state>` | Run a reconcile loop |
| `status [--all]` | Show loop status |
| `history <loop_id> [--actions]` | Show loop iteration history |

| Global Flag | Default | Description |
|-------------|---------|-------------|
| `--db` | `loops.db` | SQLite database path |

| Run Flags | Default | Description |
|-----------|---------|-------------|
| `-i`, `--inventory` | | Inventory file path |
| `--mode` | `single` | `single`, `incremental`, or `continuous` |
| `--max-iterations` | `10` | Max iterations per reconcile |
| `--interval` | `60` | Seconds between runs (continuous/incremental) |
| `--dry-run` | off | Show actions without executing |

## The Name

The Enterprise (NCC-1701) is the most iconic FTL-capable ship in science fiction. The name also describes what the project addresses — enterprise-grade concerns: persistent state, audit trails, crash recovery, concurrent loops.
