#!/usr/bin/env python3
"""
Bulk Clone Creator - Creates 20 WordPress clones for load testing
Outputs: Clone URLs and creation times only
"""

import requests
import json
import time
from datetime import datetime

# Use Traefik NLB directly to bypass SiteGround nginx interception
API_BASE = "http://k8s-traefiks-traefik-30437c81e0-7add42ef82721255.elb.us-east-1.amazonaws.com"
API_HOST_HEADER = "api.clones.betaweb.ai"
SOURCE_URL = "https://betaweb.ai"
SOURCE_USERNAME = "Charles@toctoc.com.au"
SOURCE_PASSWORD = "6(4b`Nde1i_D"
CLONE_COUNT = 5
TTL_MINUTES = 60


def create_clone(clone_id: str) -> dict:
    """Create a single WordPress clone"""
    url = f"{API_BASE}/provision"
    payload = {
        "customer_id": clone_id,
        "ttl_minutes": TTL_MINUTES,
    }
    headers = {"Host": API_HOST_HEADER, "Content-Type": "application/json"}

    start_time = time.time()
    try:
        print(f"Creating clone {clone_id}...")
        response = requests.post(url, json=payload, headers=headers, timeout=300)
        print(f"Response status: {response.status_code}")
        elapsed = time.time() - start_time
        response.raise_for_status()
        data = (
            response.json() if response.text.startswith("{") else {"raw": response.text}
        )

        clone_url = f"https://{clone_id}.clones.betaweb.ai"
        return {
            "success": True,
            "clone_id": clone_id,
            "url": clone_url,
            "elapsed_seconds": round(elapsed, 2),
            "timestamp": datetime.now().isoformat(),
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "clone_id": clone_id,
            "error": str(e),
            "elapsed_seconds": round(time.time() - start_time, 2),
        }


def main():
    print(f"\nCreating {CLONE_COUNT} clones (TTL: {TTL_MINUTES} min)...\n")

    results = []
    start = time.time()

    for i in range(1, CLONE_COUNT + 1):
        clone_id = f"bulk-test-{i:03d}"
        result = create_clone(clone_id)
        results.append(result)

        if result["success"]:
            print(f"{result['url']} - {result['elapsed_seconds']}s")
        else:
            print(f"{clone_id} - FAILED: {result['error']}")

        time.sleep(0.5)

    total_time = round(time.time() - start, 2)
    successful = [r for r in results if r["success"]]

    print(f"\n{'=' * 70}")
    print(f"SUCCESSFUL: {len(successful)}/{CLONE_COUNT}")
    print(f"TOTAL TIME: {total_time}s")
    print(f"{'=' * 70}")

    if successful:
        print("\nCLONE URLs (copy these):")
        print(f"{'=' * 70}")
        for r in successful:
            print(r["url"])
        print(f"{'=' * 70}\n")

    # Save full results
    output_file = f"bulk-clone-results-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Full results saved to: {output_file}\n")


if __name__ == "__main__":
    main()
