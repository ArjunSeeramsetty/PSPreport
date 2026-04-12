import argparse
import os
import sys
import sqlite3
from typing import Iterable, List

import pandas as pd


def _maybe_load_dotenv() -> None:

	try:
		from dotenv import load_dotenv  # type: ignore
		load_dotenv()
	except Exception:
		pass


def parse_args() -> argparse.Namespace:

	parser = argparse.ArgumentParser(
		description=(
			"Export all (or selected) SQLite tables to CSV files in a target directory."
		)
	)
	parser.add_argument(
		"--sqlite",
		help="Path to SQLite database file",
		default=os.environ.get("SQLITE_PATH", "power_data.db"),
	)
	parser.add_argument(
		"--outdir",
		help="Output directory to write CSV files",
		default=os.environ.get("CSV_EXPORT_DIR", "sqlite_csv_export"),
	)
	parser.add_argument(
		"--tables",
		nargs="*",
		help="Optional specific tables to export (defaults to all user tables)",
	)
	parser.add_argument(
		"--chunksize",
		type=int,
		help="Rows per chunk for streaming export",
		default=int(os.environ.get("CSV_EXPORT_CHUNK_SIZE", "50000")),
	)
	parser.add_argument(
		"--verbose",
		action="store_true",
		help="Verbose logging",
	)
	return parser.parse_args()


def get_user_tables(sqlite_conn: sqlite3.Connection) -> List[str]:

	cursor = sqlite_conn.execute(
		"""
		SELECT name
		FROM sqlite_master
		WHERE type='table'
			AND name NOT LIKE 'sqlite_%'
		ORDER BY name
		"""
	)
	return [row[0] for row in cursor.fetchall()]


def ensure_directory(path: str) -> None:

	os.makedirs(path, exist_ok=True)


def sanitize_filename(name: str) -> str:

	# Keep it simple: remove path separators and spaces
	return (
		name.replace("/", "_")
		.replace("\\", "_")
		.replace(" ", "_")
	)


def export_table_to_csv(
		sqlite_conn: sqlite3.Connection,
		outdir: str,
		table_name: str,
		chunksize: int,
		verbose: bool,
):

	file_name = sanitize_filename(table_name) + ".csv"
	file_path = os.path.join(outdir, file_name)

	query = f"SELECT * FROM [{table_name}]"
	first = True
	for chunk_df in pd.read_sql_query(query, sqlite_conn, chunksize=chunksize):
		if verbose:
			print(f"Writing {len(chunk_df)} rows of '{table_name}' to {file_path} (append={not first})")
		chunk_df.to_csv(
			file_path,
			mode='w' if first else 'a',
			index=False,
			header=first,
			encoding='utf-8',
		)
		first = False

	if first:
		# No data: still create an empty CSV with headers
		empty_df = pd.read_sql_query(query + " WHERE 1=0", sqlite_conn)
		empty_df.to_csv(file_path, index=False, encoding='utf-8')
		if verbose:
			print(f"Created empty CSV for table '{table_name}' at {file_path}")


def main() -> int:

	_maybe_load_dotenv()
	args = parse_args()

	if not os.path.exists(args.sqlite):
		print(f"Error: SQLite database not found at '{args.sqlite}'.", file=sys.stderr)
		return 2

	ensure_directory(args.outdir)

	try:
		sqlite_conn = sqlite3.connect(args.sqlite)
	except Exception as exc:
		print(f"Failed to open SQLite DB: {exc}", file=sys.stderr)
		return 1

	try:
		all_tables = get_user_tables(sqlite_conn)
		selected_tables: Iterable[str] = (
			args.tables if args.tables and len(args.tables) > 0 else all_tables
		)
		if args.verbose:
			print(f"Exporting {len(list(selected_tables))} tables from '{args.sqlite}' to '{args.outdir}'...")

		for table in selected_tables:
			if args.verbose:
				print(f"\n=== Exporting table: {table} ===")
			export_table_to_csv(
				sqlite_conn=sqlite_conn,
				outdir=args.outdir,
				table_name=table,
				chunksize=args.chunksize,
				verbose=args.verbose,
			)

		print("\nCSV export completed successfully.")
		return 0
	except Exception as exc:
		print(f"CSV export failed: {exc}", file=sys.stderr)
		return 1
	finally:
		try:
			sqlite_conn.close()
		except Exception:
			pass


if __name__ == "__main__":
	sys.exit(main())


