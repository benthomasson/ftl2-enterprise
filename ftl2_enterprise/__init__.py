import argparse

from .db import create_db


def cli():
    parser = argparse.ArgumentParser(description="ftl2-enterprise — database-backed multi-loop reconciler")
    parser.add_argument("--db", default="loops.db", help="SQLite database path (default: loops.db)")
    parser.add_argument("--init-db", action="store_true", help="Create database tables and exit")
    args = parser.parse_args()

    if args.init_db:
        engine = create_db(args.db)
        print(f"Database initialized: {args.db}")
        return

    parser.print_help()
