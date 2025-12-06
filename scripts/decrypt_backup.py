#!/usr/bin/env python3
"""
Atlas Backup Extraction Tool

Extracts password-protected Atlas backup ZIP files.
These are standard WinZip AES-256 encrypted ZIP files.

Compatible extraction tools:
  - 7-Zip (Windows/Linux/macOS): 7z x -p"password" backup.zip
  - WinZip, WinRAR, PeaZip
  - This script (Python 3.8+ with pyzipper)

Usage:
    python decrypt_backup.py <backup.zip> <password> [output_dir]

Requirements:
    pip install pyzipper

Example:
    python decrypt_backup.py atlas_backup_20251206.zip "MyPassword123" ./restored/
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import pyzipper
except ImportError:
    print("Error: pyzipper library is required.")
    print("Install it with: pip install pyzipper")
    sys.exit(1)


def extract_backup(zip_path: Path, password: str, output_dir: Path) -> None:
    """Extract a password-protected Atlas backup ZIP."""
    print(f"Opening backup: {zip_path}")
    
    try:
        with pyzipper.AESZipFile(zip_path, 'r') as zf:
            zf.setpassword(password.encode())
            
            # List contents
            files = zf.namelist()
            print(f"Archive contains {len(files)} files")
            
            # Try to read manifest
            try:
                import json
                with zf.open("manifest.json") as mf:
                    manifest = json.load(mf)
                    print(f"  Created: {manifest.get('created_at', 'unknown')}")
                    print(f"  Hostname: {manifest.get('hostname', 'unknown')}")
                    print(f"  Original size: {manifest.get('total_size', 0) / 1024 / 1024:.2f} MB")
            except Exception:
                pass
            
            # Extract
            print(f"\nExtracting to: {output_dir}")
            output_dir.mkdir(parents=True, exist_ok=True)
            zf.extractall(output_dir)
            
            print(f"\n✓ Successfully extracted {len(files)} files")
            
    except Exception as e:
        if "password" in str(e).lower() or "crypt" in str(e).lower():
            print(f"Error: Wrong password or corrupted archive")
        else:
            print(f"Error: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Extract password-protected Atlas backup ZIP files",
        epilog="""
Alternative extraction methods:
  - 7-Zip: 7z x -p"password" backup.zip -o./output/
  - WinZip/WinRAR: Open and enter password when prompted
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("backup_file", type=Path, help="Path to backup ZIP file")
    parser.add_argument("password", help="ZIP password")
    parser.add_argument("output_dir", type=Path, nargs="?", default=None,
                       help="Output directory (default: ./backup_restored/)")
    
    args = parser.parse_args()
    
    if not args.backup_file.exists():
        print(f"Error: Backup file not found: {args.backup_file}")
        sys.exit(1)
    
    output_dir = args.output_dir
    if output_dir is None:
        output_dir = Path("./backup_restored")
    
    extract_backup(args.backup_file, args.password, output_dir)
    print(f"\nExtraction complete!")


if __name__ == "__main__":
    main()
