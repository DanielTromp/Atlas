#!/usr/bin/env python3
"""Sanity check for Commvault cache - verify job ID sequentiality and detect gaps."""
import json
import sys
from pathlib import Path


def check_commvault_cache(cache_path: str) -> int:
    """Check Commvault cache for missing job IDs and gaps."""
    path = Path(cache_path)
    if not path.exists():
        print(f"✗ Cache file not found: {cache_path}", file=sys.stderr)
        return 1

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"✗ Failed to load cache: {e}", file=sys.stderr)
        return 1

    jobs = data.get("jobs", [])
    if not jobs:
        print("✗ No jobs found in cache", file=sys.stderr)
        return 1

    print(f"Cache: {cache_path}")
    print(f"Generated: {data.get('generated_at', 'N/A')}")
    print(f"Version: {data.get('version', 'N/A')}")
    print(f"Total jobs: {len(jobs):,}")
    print()

    # Extract job IDs
    job_ids = []
    for job in jobs:
        job_id = job.get("job_id")
        if job_id is not None:
            try:
                job_ids.append(int(job_id))
            except (ValueError, TypeError):
                print(f"⚠ Warning: Invalid job_id format: {job_id}", file=sys.stderr)

    if not job_ids:
        print("✗ No valid job IDs found", file=sys.stderr)
        return 1

    # Sort job IDs
    job_ids_sorted = sorted(job_ids)
    min_id = job_ids_sorted[0]
    max_id = job_ids_sorted[-1]
    range_size = max_id - min_id + 1

    print(f"Job ID range: {min_id:,} to {max_id:,}")
    print(f"Expected jobs in range: {range_size:,}")
    print(f"Actual jobs cached: {len(job_ids):,}")
    print()

    # Check for duplicates
    duplicates = len(job_ids) - len(set(job_ids))
    if duplicates > 0:
        print(f"⚠ Warning: Found {duplicates} duplicate job IDs")
        # Show some examples
        from collections import Counter
        counter = Counter(job_ids)
        dupes = [(jid, count) for jid, count in counter.items() if count > 1]
        for jid, count in sorted(dupes[:5]):
            print(f"  - Job ID {jid} appears {count} times")
        if len(dupes) > 5:
            print(f"  ... and {len(dupes) - 5} more")
        print()

    # Find gaps
    job_ids_set = set(job_ids)
    gaps = []
    current_gap_start = None

    for i in range(min_id, max_id + 1):
        if i not in job_ids_set:
            if current_gap_start is None:
                current_gap_start = i
        else:
            if current_gap_start is not None:
                gaps.append((current_gap_start, i - 1))
                current_gap_start = None

    # Close final gap if exists
    if current_gap_start is not None:
        gaps.append((current_gap_start, max_id))

    missing_count = range_size - len(job_ids)

    if not gaps:
        print("✓ No gaps found - all job IDs are sequential!")
        return 0

    print(f"✗ Found {len(gaps)} gap(s) with {missing_count:,} missing job IDs:")
    print()

    # Show gap details
    for idx, (start, end) in enumerate(gaps[:20], 1):
        gap_size = end - start + 1
        if gap_size == 1:
            print(f"  {idx}. Missing job ID: {start}")
        else:
            print(f"  {idx}. Missing job IDs: {start:,} to {end:,} ({gap_size:,} jobs)")

    if len(gaps) > 20:
        remaining_gaps = len(gaps) - 20
        remaining_missing = sum(end - start + 1 for start, end in gaps[20:])
        print(f"  ... and {remaining_gaps} more gaps ({remaining_missing:,} missing jobs)")

    print()

    # Calculate coverage percentage
    coverage = (len(job_ids) / range_size) * 100
    print(f"Coverage: {coverage:.2f}% of job ID range")
    print()

    # Show time range
    if jobs:
        first_job = jobs[-1]  # Jobs are sorted descending by start_time
        last_job = jobs[0]
        print(f"Oldest job: {first_job.get('start_time', 'N/A')} (ID: {first_job.get('job_id', 'N/A')})")
        print(f"Newest job: {last_job.get('start_time', 'N/A')} (ID: {last_job.get('job_id', 'N/A')})")

    return 0 if not gaps else 2


if __name__ == "__main__":
    cache_file = sys.argv[1] if len(sys.argv) > 1 else "data/commvault_backups.json"
    sys.exit(check_commvault_cache(cache_file))
