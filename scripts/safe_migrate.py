#!/usr/bin/env python3
"""Safe database migration script with backup."""

import shutil
import sys
from datetime import datetime
from pathlib import Path


def main():
    """Run migrations with automatic backup."""
    project_root = Path(__file__).resolve().parents[1]
    data_dir = project_root / "data"
    db_path = data_dir / "atlas.sqlite3"

    if not db_path.exists():
        print("No database found, running fresh migration...")
    else:
        # Create backup before any migration
        backup_name = f"atlas.sqlite3.pre_migrate_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_path = data_dir / backup_name
        shutil.copy(db_path, backup_path)
        print(f"✓ Created backup: {backup_name}")

        # Verify backup
        if backup_path.stat().st_size == db_path.stat().st_size:
            print(f"✓ Backup verified ({backup_path.stat().st_size} bytes)")
        else:
            print("✗ Backup verification failed!")
            sys.exit(1)

    # Run alembic
    import subprocess

    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )

    print(result.stdout)
    if result.returncode != 0:
        print(f"Migration failed:\n{result.stderr}")
        if db_path.exists() and "backup_path" in dir():
            print(f"Restoring from backup: {backup_name}")
            shutil.copy(backup_path, db_path)
        sys.exit(1)

    print("✓ Migration completed successfully!")


if __name__ == "__main__":
    main()
