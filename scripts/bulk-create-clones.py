#!/usr/bin/env python3
"""
Bulk Clone Creator - Creates 100 WordPress clones for load testing
Uses async v2 API with job status polling
Outputs: Clone URLs, job IDs, and creation times
"""

import requests
import json
import time
from datetime import datetime
from typing import List, Dict

# Use Traefik NLB directly to bypass SiteGround nginx interception
API_BASE = "http://k8s-traefiks-traefik-30437c81e0-7add42ef82721255.elb.us-east-1.amazonaws.com"
API_HOST_HEADER = "api.clones.betaweb.ai"
SOURCE_URL = "https://betaweb.ai"
SOURCE_USERNAME = "Charles@toctoc.com.au"
SOURCE_PASSWORD = "6(4b`Nde1i_D"
CLONE_COUNT = 100
TTL_MINUTES = 30
POLL_INTERVAL = 10  # Check job status every 10 seconds


def create_clone(clone_id: str) -> Dict:
    """Create a single WordPress clone using async v2 API"""
    url = f"{API_BASE}/api/v2/clone"
    payload = {
        "source_url": SOURCE_URL,
        "source_username": SOURCE_USERNAME,
        "source_password": SOURCE_PASSWORD,
        "customer_id": clone_id,
        "ttl_minutes": TTL_MINUTES,
    }
    headers = {"Host": API_HOST_HEADER, "Content-Type": "application/json"}

    start_time = time.time()
    try:
        print(f"Submitting clone job {clone_id}...")
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        elapsed = time.time() - start_time
        response.raise_for_status()
        data = response.json()

        job_id = data.get("job_id")
        clone_url = f"https://{clone_id}.clones.betaweb.ai"

        return {
            "success": True,
            "clone_id": clone_id,
            "job_id": job_id,
            "url": clone_url,
            "status": data.get("status", "pending"),
            "submitted_at": datetime.now().isoformat(),
            "elapsed_seconds": round(elapsed, 2),
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "clone_id": clone_id,
            "error": str(e),
            "elapsed_seconds": round(time.time() - start_time, 2),
        }


def poll_job_status(job_id: str) -> Dict:
    """Poll job status until completed or failed"""
    url = f"{API_BASE}/api/v2/job-status/{job_id}"
    headers = {"Host": API_HOST_HEADER}

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"status": "error", "error": str(e)}


def main():
    print(f"\n{'=' * 80}")
    print(f"BULK CLONE CREATOR - 100 WordPress Clones")
    print(f"TTL: {TTL_MINUTES} minutes (auto-cleanup)")
    print(f"{'=' * 80}\n")

    # Phase 1: Submit all clone jobs
    print(f"PHASE 1: Submitting {CLONE_COUNT} clone jobs...\n")
    results = []
    job_ids = []

    start = time.time()
    for i in range(1, CLONE_COUNT + 1):
        clone_id = f"load-test-{i:03d}"
        result = create_clone(clone_id)
        results.append(result)

        if result["success"]:
            job_ids.append(result["job_id"])
            print(
                f"  ✓ {clone_id} - Job: {result['job_id'][:8]}... - {result['elapsed_seconds']}s"
            )
        else:
            print(f"  ✗ {clone_id} - FAILED: {result['error']}")

        # Small delay to avoid overwhelming the API
        time.sleep(0.2)

    submit_time = round(time.time() - start, 2)
    successful = [r for r in results if r["success"]]

    print(f"\n{'=' * 80}")
    print(f"SUBMISSION COMPLETE")
    print(f"Submitted: {len(successful)}/{CLONE_COUNT} in {submit_time}s")
    print(f"{'=' * 80}\n")

    # Phase 2: Poll for completion
    print(f"PHASE 2: Monitoring job progress (polling every {POLL_INTERVAL}s)...\n")

    completed_count = 0
    failed_count = 0
    poll_start = time.time()

    while True:
        status_counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0}

        for idx, result in enumerate(results):
            if not result["success"]:
                continue

            job_id = result["job_id"]
            status = poll_job_status(job_id)

            job_status = status.get("status", "unknown")
            status_counts[job_status] = status_counts.get(job_status, 0) + 1

            # Update result with latest status
            results[idx]["status"] = job_status
            results[idx]["progress"] = status.get("progress", 0)

            if job_status == "completed" and result.get("status") != "completed":
                completed_count += 1
                print(
                    f"  ✓ {result['clone_id']} COMPLETED - {status.get('result', {}).get('public_url', 'N/A')}"
                )
            elif job_status == "failed" and result.get("status") != "failed":
                failed_count += 1
                print(
                    f"  ✗ {result['clone_id']} FAILED - {status.get('error', 'Unknown error')}"
                )

        # Print progress summary
        total_done = status_counts["completed"] + status_counts["failed"]
        total_jobs = len(successful)
        progress_pct = round((total_done / total_jobs) * 100) if total_jobs > 0 else 0

        print(
            f"\n  Progress: {total_done}/{total_jobs} ({progress_pct}%) - "
            f"Pending: {status_counts['pending']}, Running: {status_counts['running']}, "
            f"Completed: {status_counts['completed']}, Failed: {status_counts['failed']}"
        )

        if total_done == total_jobs:
            break

        time.sleep(POLL_INTERVAL)

    total_time = round(time.time() - poll_start, 2)

    # Final summary
    print(f"\n{'=' * 80}")
    print(f"LOAD TEST COMPLETE")
    print(f"Total Time: {total_time}s ({round(total_time / 60, 1)} minutes)")
    print(f"Completed: {status_counts['completed']}/{CLONE_COUNT}")
    print(f"Failed: {status_counts['failed']}/{CLONE_COUNT}")
    print(
        f"Success Rate: {round((status_counts['completed'] / CLONE_COUNT) * 100, 1)}%"
    )
    print(f"{'=' * 80}\n")

    # Print all successful clone URLs
    successful_clones = [r for r in results if r.get("status") == "completed"]
    if successful_clones:
        print(f"SUCCESSFUL CLONE URLs (copy these):")
        print(f"{'=' * 80}")
        for r in successful_clones:
            print(r["url"])
        print(f"{'=' * 80}\n")

    # Save full results
    output_file = f"bulk-clone-results-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    with open(output_file, "w") as f:
        json.dump(
            {
                "test_config": {
                    "clone_count": CLONE_COUNT,
                    "ttl_minutes": TTL_MINUTES,
                    "source_url": SOURCE_URL,
                    "timestamp": datetime.now().isoformat(),
                    "submit_time_seconds": submit_time,
                    "total_time_seconds": total_time,
                },
                "results": results,
                "summary": {
                    "submitted": len(successful),
                    "completed": status_counts["completed"],
                    "failed": status_counts["failed"],
                    "success_rate": round(
                        (status_counts["completed"] / CLONE_COUNT) * 100, 1
                    ),
                },
            },
            f,
            indent=2,
        )

    print(f"Full results saved to: {output_file}\n")

    # Print cleanup reminder
    print(f"{'=' * 80}")
    print(f"REMINDER: Clones will auto-delete after {TTL_MINUTES} minutes")
    print(f"To manually delete, run: python3 scripts/delete-clones.py")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
