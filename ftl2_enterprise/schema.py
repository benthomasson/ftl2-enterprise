from sqlalchemy import MetaData, Table, Column, Integer, Text, REAL, ForeignKey

metadata = MetaData()

loops = Table(
    "loops",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("status", Text, nullable=False, default="pending"),
    Column("mode", Text, nullable=False, default="single"),
    Column("desired_state", Text),
    Column("inventory", Text),
    Column("groups", Text),  # JSON array
    Column("interval", REAL),
    Column("created_at", Text, nullable=False, server_default="(datetime('now'))"),
    Column("started_at", Text),
    Column("completed_at", Text),
)

increments = Table(
    "increments",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("loop_id", Integer, ForeignKey("loops.id"), nullable=False),
    Column("n", Integer, nullable=False),
    Column("desired_state", Text, nullable=False),
    Column("status", Text, nullable=False, default="pending"),
    Column("is_fix", Integer, nullable=False, default=0),
    Column("created_at", Text, nullable=False, server_default="(datetime('now'))"),
    Column("completed_at", Text),
)

iterations = Table(
    "iterations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("loop_id", Integer, ForeignKey("loops.id"), nullable=False),
    Column("increment_id", Integer, ForeignKey("increments.id")),
    Column("n", Integer, nullable=False),
    Column("phase", Text, nullable=False, default="observing"),
    Column("converged", Integer),
    Column("reasoning", Text),
    Column("observations", Text),  # JSON
    Column("created_at", Text, nullable=False, server_default="(datetime('now'))"),
    Column("completed_at", Text),
)

hosts = Table(
    "hosts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("loop_id", Integer, ForeignKey("loops.id"), nullable=False),
    Column("hostname", Text, nullable=False),
    Column("ansible_host", Text),
    Column("ansible_user", Text),
    Column("ansible_port", Integer),
    Column("groups", Text),  # JSON array
    Column("facts", Text),  # JSON
    Column("status", Text, nullable=False, default="unknown"),
    Column("created_at", Text, nullable=False, server_default="(datetime('now'))"),
    Column("updated_at", Text),
)

actions = Table(
    "actions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("iteration_id", Integer, ForeignKey("iterations.id"), nullable=False),
    Column("host_id", Integer, ForeignKey("hosts.id")),
    Column("module", Text, nullable=False),
    Column("params", Text),  # JSON
    Column("status", Text, nullable=False, default="pending"),
    Column("rc", Integer),
    Column("stdout", Text),
    Column("stderr", Text),
    Column("changed", Integer),
    Column("started_at", Text),
    Column("completed_at", Text),
)

prompts = Table(
    "prompts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("loop_id", Integer, ForeignKey("loops.id"), nullable=False),
    Column("iteration_id", Integer, ForeignKey("iterations.id")),
    Column("prompt_text", Text, nullable=False),
    Column("options", Text),  # JSON array
    Column("response", Text),
    Column("status", Text, nullable=False, default="pending"),
    Column("created_at", Text, nullable=False, server_default="(datetime('now'))"),
    Column("answered_at", Text),
)

resources = Table(
    "resources",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("loop_id", Integer, ForeignKey("loops.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("data", Text),  # JSON
    Column("created_at", Text, nullable=False, server_default="(datetime('now'))"),
    Column("updated_at", Text),
)

rule_results = Table(
    "rule_results",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("iteration_id", Integer, ForeignKey("iterations.id"), nullable=False),
    Column("rule_name", Text, nullable=False),
    Column("condition", Text),
    Column("matched", Integer, nullable=False),
    Column("approved", Integer),
    Column("reasoning", Text),
    Column("created_at", Text, nullable=False, server_default="(datetime('now'))"),
)
