#!/usr/bin/env python3
"""
Bulk Clone Creator - Creates 50 WordPress clones for load testing
Uses async v2 API with job status polling
Outputs: Clone URLs, credentials, job IDs, and creation times
"""

import requests
import json
import time
from datetime import datetime
from typing import List, Dict

# Use public ALB endpoint (clones.betaweb.ai)
API_BASE = "https://clones.betaweb.ai"
API_HOST_HEADER = "clones.betaweb.ai"

# Source configurations - alternate between both sites
SOURCES = [
    {
        "url": "https://betaweb.ai",
        "username": "Charles@toctoc.com.au",
        "password": "6(4b`Nde1i_D",
    },
    {
        "url": "https://bonnel.ai",
        "username": "charles@toctoc.com.au",
        "password": "6(4b`Nde1i_D",
    },
]

CLONE_COUNT = 30  # Testing with AWS 64 vCPU quota
TTL_MINUTES = 30
POLL_INTERVAL = 10  # Check job status every 10 seconds


def create_clone(clone_id: str, source_index: int) -> Dict:
    """Create a single WordPress clone using async v2 API"""
    url = f"{API_BASE}/api/v2/clone"
    source = SOURCES[source_index % len(SOURCES)]
    payload = {
        "source_url": source["url"],
        "source_username": source["username"],
        "source_password": source["password"],
        "customer_id": clone_id,
        "ttl_minutes": TTL_MINUTES,
    }
    headers = {"Host": API_HOST_HEADER, "Content-Type": "application/json"}

    start_time = time.time()
    try:
        print(f"Submitting clone job {clone_id} from {source['url']}...")
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
            "source_url": source["url"],
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
    url = f"{API_BASE}/api/v2/jobs/{job_id}"
    headers = {"Host": API_HOST_HEADER}

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"status": "error", "error": str(e)}


def get_clone_credentials(clone_id: str, retries: int = 10) -> Dict:
    """Fetch credentials from Kubernetes secret with retry"""
    import subprocess
    import base64

    for attempt in range(retries):
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "secret",
                    f"{clone_id}-credentials",
                    "-n",
                    "wordpress-staging",
                    "-o",
                    "jsonpath={.data}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout and result.stdout != "{}":
                data = json.loads(result.stdout)
                wp_password = "N/A"
                wp_username = "admin"
                api_key = ""

                if data.get("wordpress-password"):
                    try:
                        wp_password = base64.b64decode(
                            data["wordpress-password"]
                        ).decode()
                    except:
                        wp_password = "decode-error"

                if data.get("wordpress-username"):
                    try:
                        wp_username = base64.b64decode(
                            data["wordpress-username"]
                        ).decode()
                    except:
                        pass

                if data.get("api-key"):
                    try:
                        api_key = base64.b64decode(data["api-key"]).decode()
                    except:
                        pass

                return {
                    "wordpress_username": wp_username,
                    "wordpress_password": wp_password,
                    "api_key": api_key,
                }
        except Exception as e:
            print(f"  Warning: Credential fetch failed for {clone_id}: {e}")
        if attempt < retries - 1:
            time.sleep(3)
    return {"wordpress_username": "admin", "wordpress_password": "N/A", "api_key": ""}


def main():
    print(f"\n{'=' * 80}")
    print(f"BULK CLONE CREATOR - {CLONE_COUNT} WordPress Clones (Phase 2 Optimized)")
    print(f"TTL: {TTL_MINUTES} minutes (auto-cleanup)")
    print(f"Features: Parallel execution + Warm pool + Redis caching")
    print(f"{'=' * 80}\n")

    # Phase 1: Submit all clone jobs
    print(f"PHASE 1: Submitting {CLONE_COUNT} clone jobs...\n")
    results = []
    job_ids = []

    start = time.time()
    for i in range(1, CLONE_COUNT + 1):
        clone_id = f"load-test-{i:03d}"
        # Alternate between sources: even numbers use index 0 (betaweb), odd use index 1 (bonnel)
        source_index = (i - 1) % 2
        result = create_clone(clone_id, source_index)
        results.append(result)

        if result["success"]:
            job_ids.append(result["job_id"])
            source_name = result.get("source_url", "").split("//")[1].split("/")[0]
            print(
                f"  ✓ {clone_id} ({source_name}) - Job: {result['job_id'][:8]}... - {result['elapsed_seconds']}s"
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
                result_data = status.get("result", {})
                public_url = result_data.get("public_url", "N/A")
                print(f"  ✓ {result['clone_id']} COMPLETED - {public_url}")
                # Fetch credentials from Kubernetes secret
                creds = get_clone_credentials(result["clone_id"])
                results[idx]["wordpress_username"] = creds["wordpress_username"]
                results[idx]["wordpress_password"] = creds["wordpress_password"]
                results[idx]["api_key"] = creds["api_key"]
                results[idx]["public_url"] = public_url
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
    avg_time = (
        round(total_time / status_counts["completed"], 2)
        if status_counts["completed"] > 0
        else 0
    )
    print(f"Average Clone Time: {avg_time}s")
    print(f"{'=' * 80}\n")

    # Define output files
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_file = f"bulk-clone-results-{timestamp}.json"
    credentials_file = f"bulk-clone-credentials-{timestamp}.json"

    # Print all successful clone URLs with credentials
    successful_clones = [r for r in results if r.get("status") == "completed"]
    if successful_clones:
        print(f"SUCCESSFUL CLONES - URLs and Credentials:")
        print(f"{'=' * 80}")
        print(f"{'Clone ID':<20} {'Public URL':<50} {'Username':<15}")
        print(f"{'-' * 80}")
        for r in successful_clones:
            clone_id = r["clone_id"]
            public_url = r.get("public_url", r["url"])
            username = r.get("wordpress_username", "admin")
            print(f"{clone_id:<20} {public_url:<50} {username:<15}")
        print(f"{'-' * 80}")
        print(f"\nPasswords saved to: {credentials_file}")
        print(f"\nHOW TO ACCESS CLONES:")
        print(
            f"  1. Open browser to any URL above (e.g., https://load-test-001.clones.betaweb.ai)"
        )
        print(f"  2. Login with credentials from {credentials_file}")
        print(f"  3. Admin panel: https://<clone_id>.clones.betaweb.ai/wp-admin")
        print(f"{'=' * 80}\n")

    # Save full results
    with open(output_file, "w") as f:
        json.dump(
            {
                "test_config": {
                    "clone_count": CLONE_COUNT,
                    "ttl_minutes": TTL_MINUTES,
                    "sources": [s["url"] for s in SOURCES],
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

    # Save clean credentials file (easy to read/use)
    credentials_data = {
        "test_timestamp": datetime.now().isoformat(),
        "ttl_minutes": TTL_MINUTES,
        "total_clones": len(successful_clones),
        "clones": [
            {
                "clone_id": r["clone_id"],
                "public_url": r.get("public_url", r["url"]),
                "wordpress_username": r.get("wordpress_username", "admin"),
                "wordpress_password": r.get("wordpress_password", "N/A"),
                "api_key": r.get("api_key", ""),
            }
            for r in successful_clones
        ],
    }
    with open(credentials_file, "w") as f:
        json.dump(credentials_data, f, indent=2)

    print(f"Full results saved to: {output_file}")
    print(f"Credentials saved to: {credentials_file}\n")

    # Print cleanup reminder
    print(f"{'=' * 80}")
    print(f"REMINDER: Clones will auto-delete after {TTL_MINUTES} minutes")
    print(f"To manually delete, run: python3 scripts/delete-clones.py")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
