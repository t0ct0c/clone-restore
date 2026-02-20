#!/usr/bin/env python3
"""
Bulk Clone Deleter - Deletes WordPress clones and all associated Kubernetes resources

Supports:
- Delete via API (calls /api/v2/delete endpoint)
- Direct Kubernetes cleanup (deployments, services, ingresses, secrets)
- Pattern-based deletion (load-test-*, bulk-test-*, concurrent-*, etc.)

Usage:
  python3 delete-clones.py <results-file.json>    # Delete clones from results file
  python3 delete-clones.py --all                  # Delete ALL test clones
  python3 delete-clones.py --pattern "load-test"  # Delete clones matching pattern
  python3 delete-clones.py --k8s-only             # Only cleanup K8s resources (no API)
"""

import requests
import json
import sys
import subprocess
import re
from datetime import datetime
from typing import List, Tuple

API_BASE = "http://k8s-traefiks-traefik-30437c81e0-7add42ef82721255.elb.us-east-1.amazonaws.com"
API_HOST_HEADER = "api.clones.betaweb.ai"
NAMESPACE = "wordpress-staging"


def run_kubectl(args: List[str]) -> Tuple[bool, str]:
    """Run kubectl command and return success status and output"""
    try:
        result = subprocess.run(
            ["kubectl"] + args, capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0, result.stdout.strip()
    except Exception as e:
        return False, str(e)


def delete_via_api(clone_id: str) -> dict:
    """Delete clone via API endpoint"""
    url = f"{API_BASE}/api/v2/delete"
    payload = {"customer_id": clone_id}
    headers = {"Host": API_HOST_HEADER, "Content-Type": "application/json"}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        return {
            "success": response.status_code in [200, 204],
            "clone_id": clone_id,
            "method": "api",
            "status_code": response.status_code,
            "response": response.text[:200] if response.text else "No content",
        }
    except Exception as e:
        return {
            "success": False,
            "clone_id": clone_id,
            "method": "api",
            "error": str(e),
        }


def delete_k8s_resources(clone_id: str) -> dict:
    """Delete all Kubernetes resources for a clone"""
    results = {
        "clone_id": clone_id,
        "method": "k8s",
        "deployment": False,
        "service": False,
        "ingress": False,
        "secret": False,
    }

    # Delete Deployment
    success, _ = run_kubectl(
        [
            "delete",
            "deployment",
            clone_id,
            "-n",
            NAMESPACE,
            "--ignore-not-found=true",
            "--request-timeout=10s",
        ]
    )
    results["deployment"] = success

    # Delete Service
    success, _ = run_kubectl(
        [
            "delete",
            "service",
            clone_id,
            "-n",
            NAMESPACE,
            "--ignore-not-found=true",
            "--request-timeout=10s",
        ]
    )
    results["service"] = success

    # Delete Ingress
    success, _ = run_kubectl(
        [
            "delete",
            "ingress",
            clone_id,
            "-n",
            NAMESPACE,
            "--ignore-not-found=true",
            "--request-timeout=10s",
        ]
    )
    results["ingress"] = success

    # Delete Secret
    success, _ = run_kubectl(
        [
            "delete",
            "secret",
            f"{clone_id}-credentials",
            "-n",
            NAMESPACE,
            "--ignore-not-found=true",
            "--request-timeout=10s",
        ]
    )
    results["secret"] = success

    # Overall success if at least deployment was deleted
    results["success"] = results["deployment"]

    return results


def list_test_clones(pattern: str = None) -> List[str]:
    """List test clone deployments from Kubernetes"""
    if pattern:
        # Get deployments matching pattern
        success, output = run_kubectl(
            [
                "get",
                "deployments",
                "-n",
                NAMESPACE,
                "-l",
                "app=wordpress-clone",
                "-o",
                "jsonpath='{range .items[*]}{.metadata.name}{\"\\n\"}{end}'",
            ]
        )
        if success:
            all_clones = [name.strip("'") for name in output.split("\n") if name]
            return [name for name in all_clones if pattern in name]
    else:
        # Get all test clones (load-test-*, bulk-test-*, concurrent-*, test-*)
        success, output = run_kubectl(
            [
                "get",
                "deployments",
                "-n",
                NAMESPACE,
                "-o",
                "jsonpath='{range .items[*]}{.metadata.name}{\"\\n\"}{end}'",
            ]
        )
        if success:
            all_clones = [name.strip("'") for name in output.split("\n") if name]
            test_prefixes = [
                "load-test-",
                "bulk-test-",
                "concurrent",
                "test-",
                "final-test",
            ]
            return [
                name
                for name in all_clones
                if any(name.startswith(p) for p in test_prefixes)
            ]

    return []


def extract_clone_ids_from_file(filepath: str) -> list:
    """Extract clone IDs from results file"""
    with open(filepath, "r") as f:
        data = json.load(f)

    # Handle both old format (list) and new format (dict with results key)
    if isinstance(data, list):
        return [r["clone_id"] for r in data if r.get("success") or r.get("clone_id")]
    elif isinstance(data, dict) and "results" in data:
        return [r["clone_id"] for r in data["results"] if r.get("clone_id")]

    return []


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    clone_ids = []
    k8s_only = "--k8s-only" in sys.argv
    use_api = not k8s_only

    # Parse arguments
    if sys.argv[1] == "--all":
        print("WARNING: This will delete ALL test clones!")
        print("Matching patterns: load-test-*, bulk-test-*, concurrent-*, test-*\n")
        confirm = input("Type 'yes' to confirm: ")
        if confirm.lower() != "yes":
            print("Aborted.")
            sys.exit(0)
        clone_ids = list_test_clones()
        print(f"Found {len(clone_ids)} test clones in Kubernetes\n")

    elif sys.argv[1] == "--pattern":
        if len(sys.argv) < 3:
            print("Error: --pattern requires a pattern argument")
            sys.exit(1)
        pattern = sys.argv[2]
        print(f"Finding clones matching pattern: {pattern}\n")
        clone_ids = list_test_clones(pattern)
        print(f"Found {len(clone_ids)} clones\n")

    elif sys.argv[1] == "--k8s-only":
        print("Kubernetes-only mode: Will delete K8s resources directly\n")
        clone_ids = list_test_clones()
        print(f"Found {len(clone_ids)} test clones\n")

    else:
        filepath = sys.argv[1]
        try:
            clone_ids = extract_clone_ids_from_file(filepath)
            print(f"Loaded {len(clone_ids)} clone IDs from {filepath}\n")
        except FileNotFoundError:
            print(f"File not found: {filepath}")
            sys.exit(1)
        except json.JSONDecodeError:
            print(f"Invalid JSON: {filepath}")
            sys.exit(1)

    if not clone_ids:
        print("No clones found to delete.")
        sys.exit(0)

    print(f"Deleting {len(clone_ids)} clones...\n")
    print(f"{'=' * 80}")

    results = []
    start = datetime.now()

    for i, clone_id in enumerate(clone_ids, 1):
        result = None

        if use_api:
            # Try API first, fallback to kubectl
            result = delete_via_api(clone_id)
            if not result["success"]:
                # Fallback to kubectl
                result = delete_k8s_resources(clone_id)
        else:
            # k8s-only mode
            result = delete_k8s_resources(clone_id)

        results.append(result)

        # Print status
        if result.get("success"):
            status = "✓ DELETED"
            if result.get("method") == "k8s":
                deleted = []
                if result.get("deployment"):
                    deleted.append("deployment")
                if result.get("service"):
                    deleted.append("service")
                if result.get("ingress"):
                    deleted.append("ingress")
                if result.get("secret"):
                    deleted.append("secret")
                status += f" ({', '.join(deleted)})"
        else:
            status = "✗ FAILED"
            error = result.get("error", result.get("response", "Unknown"))
            status += f" - {error[:50]}"

        print(f"[{i:3d}/{len(clone_ids)}] {clone_id} - {status}")

    elapsed = (datetime.now() - start).total_seconds()
    successful = sum(1 for r in results if r.get("success"))

    print(f"{'=' * 80}")
    print(f"\nDELETION COMPLETE")
    print(f"Deleted: {successful}/{len(clone_ids)}")
    print(f"Failed: {len(clone_ids) - successful}/{len(clone_ids)}")
    print(f"Time: {elapsed:.1f}s")
    print(f"{'=' * 80}\n")

    # Print failed deletions
    failed = [r for r in results if not r.get("success")]
    if failed:
        print("FAILED DELETIONS:")
        for r in failed:
            print(
                f"  - {r['clone_id']}: {r.get('error', r.get('response', 'Unknown'))}"
            )
        print()


if __name__ == "__main__":
    main()
