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
# Run directly from GitHub
uvx --from "git+https://github.com/benthomasson/ftl2-enterprise" \
    ftl2-enterprise --init-db

# Or install locally
pip install -e .
ftl2-enterprise --init-db
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

## CLI Options

```
ftl2-enterprise [--db PATH] [--init-db]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--db` | `loops.db` | SQLite database path |
| `--init-db` | off | Create tables and exit |

## The Name

The Enterprise (NCC-1701) is the most iconic FTL-capable ship in science fiction. The name also describes what the project addresses — enterprise-grade concerns: persistent state, audit trails, crash recovery, concurrent loops.
