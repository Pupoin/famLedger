"""Mosaic maintenance CLI -- export, import and verify a data directory.

    python -m cli export  --out /tmp/mosaic-export.tar.gz
    python -m cli import  --archive /tmp/mosaic-export.tar.gz
    python -m cli verify
    python -m cli inspect --archive /tmp/mosaic-export.tar.gz

Deliberately imports neither ``config`` nor ``main``: ``config`` raises when
SECRET_KEY is unset, and needing a session-signing secret in order to *rescue
your data* would be a poor arrangement. This module only ever touches SQLite
files and tar archives.

Inside a container:

    docker compose run --rm mosaic python -m cli verify
"""

import argparse
import logging
import sys
from pathlib import Path

from services.portable import (
    compute_fingerprint,
    export_archive,
    format_fingerprint,
    import_archive,
    read_manifest,
)
from version import __version__


def _resolve_data_dir(explicit) -> Path:
    """Where the data lives: --data-dir, else DATA_DIR, else the backend dir.

    Imported from ``database`` rather than recomputed so there is exactly one
    definition of DATA_DIR in the codebase.
    """
    if explicit:
        return Path(explicit)
    import database
    return Path(database.DATA_DIR)


def _cmd_export(args) -> int:
    data_dir = _resolve_data_dir(args.data_dir)
    dest = Path(args.out)
    manifest = export_archive(data_dir, dest, app_version=__version__)
    size_mb = dest.stat().st_size / (1024 * 1024)

    print(f"Exported {data_dir} -> {dest}  ({size_mb:.1f} MB)")
    print(f"  mosaic version : {manifest['mosaic_version']}")
    print(f"  schema version : {manifest['schema_version']}")
    print(f"  db sha256      : {manifest['db_sha256']}")
    print()
    print("Data fingerprint (compare this against the destination after import):")
    print(format_fingerprint(manifest["fingerprint"]))
    return 0


def _cmd_import(args) -> int:
    data_dir = _resolve_data_dir(args.data_dir)
    result = import_archive(Path(args.archive), data_dir, force=args.force)
    manifest = result["manifest"]

    print(f"Imported {args.archive} -> {data_dir}")
    print(f"  exported by    : mosaic {manifest['mosaic_version']}")
    print(f"  exported at    : {manifest['exported_at']}")
    if result["snapshot"]:
        print(f"  prior db saved : {result['snapshot']}")
    print()
    print("Verified fingerprint of the imported data:")
    print(format_fingerprint(result["fingerprint"]))
    print()
    print("Checksum and fingerprint both verified. Start the app to let it stamp")
    print("the schema version. Development mode does not create automatic backups.")
    return 0


def _cmd_verify(args) -> int:
    if args.db:
        db_path = Path(args.db)
    else:
        db_path = _resolve_data_dir(args.data_dir) / "famledger.db"
    if not db_path.exists():
        print(f"No database at {db_path}", file=sys.stderr)
        return 1

    print(f"Database: {db_path}")
    print()
    print(format_fingerprint(compute_fingerprint(db_path)))
    return 0


def _cmd_inspect(args) -> int:
    manifest = read_manifest(Path(args.archive))
    print(f"Archive: {args.archive}")
    print(f"  archive format : {manifest.get('format')}")
    print(f"  mosaic version : {manifest.get('mosaic_version')}")
    print(f"  schema version : {manifest.get('schema_version')}")
    print(f"  exported at    : {manifest.get('exported_at')}")
    print(f"  db sha256      : {manifest.get('db_sha256')}")
    print(f"  includes       : {manifest.get('includes')}")
    print()
    print(format_fingerprint(manifest.get("fingerprint", {})))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cli",
        description="Mosaic data export / import / verification.",
    )
    parser.add_argument(
        "--data-dir",
        help="Override the data directory (default: $DATA_DIR, else backend/).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_export = sub.add_parser(
        "export", help="Write a verifiable archive of the data directory."
    )
    p_export.add_argument("--out", required=True, help="Destination .tar.gz path.")
    p_export.set_defaults(func=_cmd_export)

    p_import = sub.add_parser(
        "import", help="Restore an archive, verifying checksum and fingerprint."
    )
    p_import.add_argument("--archive", required=True, help="Archive to restore.")
    p_import.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing non-empty database (a snapshot is taken first).",
    )
    p_import.set_defaults(func=_cmd_import)

    p_verify = sub.add_parser(
        "verify", help="Print the data fingerprint of a live database."
    )
    p_verify.add_argument("--db", help="Path to a famledger.db (default: <data-dir>/famledger.db).")
    p_verify.set_defaults(func=_cmd_verify)

    p_inspect = sub.add_parser(
        "inspect", help="Show an archive's manifest without extracting it."
    )
    p_inspect.add_argument("--archive", required=True)
    p_inspect.set_defaults(func=_cmd_inspect)

    return parser


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 -- a CLI should not traceback at a user
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
