#!/usr/bin/env python3
"""
Clone a single WordPress site and show credentials
Usage: python3 scripts/clone-single.py <clone-name>
"""

import requests
import time
import subprocess
import base64
import json
import sys

API_BASE = "http://k8s-traefiks-traefik-30437c81e0-7add42ef82721255.elb.us-east-1.amazonaws.com"
API_HOST = "api.clones.betaweb.ai"
SOURCE_URL = "https://betaweb.ai"
SOURCE_USERNAME = "Charles@toctoc.com.au"
SOURCE_PASSWORD = "6(4b`Nde1i_D"


def get_credentials(clone_id, retries=10):
    """Fetch credentials from Kubernetes secret"""
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
                timeout=5,
            )
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                return {
                    "username": base64.b64decode(
                        data.get("wordpress-username", "")
                    ).decode()
                    if data.get("wordpress-username")
                    else "admin",
                    "password": base64.b64decode(
                        data.get("wordpress-password", "")
                    ).decode()
                    if data.get("wordpress-password")
                    else None,
                }
        except:
            pass
        if attempt < retries - 1:
            time.sleep(3)
    return None


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/clone-single.py <clone-name>")
        print("Example: python3 scripts/clone-single.py my-test-site")
        sys.exit(1)

    clone_id = sys.argv[1]

    print(f"\n🚀 Creating WordPress clone: {clone_id}")
    print("=" * 60)

    # Create clone
    url = f"{API_BASE}/api/v2/clone"
    payload = {
        "source_url": SOURCE_URL,
        "source_username": SOURCE_USERNAME,
        "source_password": SOURCE_PASSWORD,
        "customer_id": clone_id,
        "ttl_minutes": 30,
    }
    headers = {"Host": API_HOST, "Content-Type": "application/json"}

    response = requests.post(url, json=payload, headers=headers, timeout=60)
    if response.status_code != 200:
        print(f"❌ Failed to create clone: {response.text}")
        sys.exit(1)

    job_id = response.json().get("job_id")
    print(f"✓ Job submitted: {job_id}")
    print("⏳ Waiting for clone to be ready...")

    # Poll for completion
    for i in range(30):
        time.sleep(5)
        status_url = f"{API_BASE}/api/v2/job-status/{job_id}"
        status_response = requests.get(status_url, headers=headers, timeout=30)
        status = status_response.json().get("status", "unknown")

        if status == "completed":
            print(f"✓ Clone completed! ({i * 5}s)")
            break
        elif status == "failed":
            print(f"❌ Clone failed: {status_response.json().get('error', 'Unknown')}")
            sys.exit(1)
        else:
            print(f"  Status: {status}...")

    # Get credentials
    print("\n🔑 Fetching credentials...")
    creds = get_credentials(clone_id)

    if creds and creds.get("password"):
        print("=" * 60)
        print("✅ CLONE READY!")
        print("=" * 60)
        print(f"\n📍 URL:      https://{clone_id}.clones.betaweb.ai")
        print(f"👤 Username: {creds['username']}")
        print(f"🔒 Password: {creds['password']}")
        print(f"\n🔧 Admin URL: https://{clone_id}.clones.betaweb.ai/wp-admin")
        print("=" * 60)
        print("\n⏰ Clone will auto-delete after 30 minutes")
        print(
            f"To delete manually: kubectl delete deployment,service,ingress,secret -n wordpress-staging -l clone-id={clone_id}"
        )
    else:
        print("⚠️  Clone created but credentials not found yet.")
        print(
            f"   Try: kubectl get secret {clone_id}-credentials -n wordpress-staging -o jsonpath='{{.data}}'"
        )


if __name__ == "__main__":
    main()
