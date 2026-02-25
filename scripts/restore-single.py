#!/usr/bin/env python3
"""
Restore from one WordPress site to another using async API
Usage: python3 scripts/restore-single.py
"""

import requests
import time
import sys
from datetime import datetime

API_BASE = "https://clones.betaweb.ai"
API_HOST = "clones.betaweb.ai"

# Source (clone or regular WordPress site)
SOURCE_URL = "https://e2e-restore-test.clones.betaweb.ai/"  # Change to your clone URL
SOURCE_USERNAME = "admin"
SOURCE_PASSWORD = "WpNKQBnBCk6obYXo4pcqCzJZtNLjRWk4"  # Change to your clone password

# Target (production site)
TARGET_URL = "https://betaweb.ai/"  # Change to your target URL
TARGET_USERNAME = "Charles@toctoc.com.au"
TARGET_PASSWORD = "6(4b`Nde1i_D"  # Change to your target password


def main():
    customer_id = f"restore-test-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    print(f"\n🚀 Starting WordPress restore: {customer_id}")
    print("=" * 60)
    print(f"Source: {SOURCE_URL}")
    print(f"Target: {TARGET_URL}")
    print("=" * 60)

    # Create restore job
    url = f"{API_BASE}/api/v2/restore"
    payload = {
        "source_url": SOURCE_URL,
        "source_username": SOURCE_USERNAME,
        "source_password": SOURCE_PASSWORD,
        "target_url": TARGET_URL,
        "target_username": TARGET_USERNAME,
        "target_password": TARGET_PASSWORD,
        "preserve_plugins": True,  # Keep target plugins
        "preserve_themes": False,  # Replace with source themes
        "customer_id": customer_id,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Host": API_HOST},
            timeout=10,
        )
        response.raise_for_status()
        job = response.json()
        job_id = job.get("job_id")

        if not job_id:
            print(f"❌ Failed to create restore job: {job}")
            sys.exit(1)

        print(f"✓ Job submitted: {job_id}")
        print(f"⏳ Waiting for restore to complete...")

        # Poll for job status
        status_url = f"{API_BASE}/api/v2/job-status/{job_id}"
        start_time = time.time()

        while True:
            try:
                status_response = requests.get(
                    status_url,
                    headers={"Host": API_HOST},
                    timeout=10,
                )
                status_response.raise_for_status()
                job_status = status_response.json()

                status = job_status.get("status")
                progress = job_status.get("progress", 0)
                error = job_status.get("error")

                print(f"  Status: {status} ({progress}%)")

                if status == "completed":
                    duration = int(time.time() - start_time)
                    print(f"✓ Restore completed! ({duration}s)")
                    print("=" * 60)

                    result = job_status.get("result", {})
                    if result:
                        print("\n📊 Restore Result:")
                        print("=" * 60)
                        print(f"Success: {result.get('success', False)}")
                        print(f"Message: {result.get('message', 'N/A')}")

                        integrity = result.get("integrity", {})
                        if integrity:
                            print(f"\nIntegrity Check:")
                            print(f"  Status: {integrity.get('status', 'N/A')}")
                            warnings = integrity.get("warnings", [])
                            if warnings:
                                print(f"  Warnings: {len(warnings)}")
                                for warning in warnings[:5]:  # Show first 5
                                    print(f"    - {warning}")

                        print("=" * 60)
                    break

                elif status == "failed":
                    duration = int(time.time() - start_time)
                    print(f"❌ Restore failed after {duration}s: {error}")
                    sys.exit(1)

                time.sleep(5)  # Poll every 5 seconds

            except requests.RequestException as e:
                print(f"⚠️  Status check error: {e}")
                time.sleep(5)

    except requests.RequestException as e:
        print(f"❌ Failed to create restore job: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
