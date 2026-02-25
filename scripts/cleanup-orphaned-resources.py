#!/usr/bin/env python3
"""
Cleanup orphaned Services and Ingresses in wordpress-staging namespace.
Only removes resources that have no corresponding Deployment.

Usage:
    python cleanup-orphaned-resources.py           # Interactive mode
    python cleanup-orphaned-resources.py --yes     # Auto-confirm deletion
"""

import subprocess
import json
import sys
import argparse

NAMESPACE = "wordpress-staging"
PROTECTED_SERVICES = ["redis-master", "wp-k8s-service"]
PROTECTED_INGRESSES = ["wp-k8s-service"]


def get_deployments():
    """Get all deployment names"""
    result = subprocess.run(
        ["kubectl", "get", "deployments", "-n", NAMESPACE, "-o", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error getting deployments: {result.stderr}")
        return set()

    data = json.loads(result.stdout)
    return {item["metadata"]["name"] for item in data.get("items", [])}


def get_services():
    """Get all service names"""
    result = subprocess.run(
        ["kubectl", "get", "services", "-n", NAMESPACE, "-o", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error getting services: {result.stderr}")
        return set()

    data = json.loads(result.stdout)
    return {item["metadata"]["name"] for item in data.get("items", [])}


def get_ingresses():
    """Get all ingress names"""
    result = subprocess.run(
        ["kubectl", "get", "ingress", "-n", NAMESPACE, "-o", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error getting ingresses: {result.stderr}")
        return set()

    data = json.loads(result.stdout)
    return {item["metadata"]["name"] for item in data.get("items", [])}


def get_secrets():
    """Get all secret names ending with -credentials"""
    result = subprocess.run(
        ["kubectl", "get", "secrets", "-n", NAMESPACE, "-o", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error getting secrets: {result.stderr}")
        return set()

    data = json.loads(result.stdout)
    # Only return secrets ending with -credentials
    return {
        item["metadata"]["name"]
        for item in data.get("items", [])
        if item["metadata"]["name"].endswith("-credentials")
    }


def delete_service(name):
    """Delete a service"""
    result = subprocess.run(
        ["kubectl", "delete", "service", name, "-n", NAMESPACE],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"  ✓ Deleted service: {name}")
        return True
    else:
        print(f"  ✗ Failed to delete service {name}: {result.stderr}")
        return False


def delete_ingress(name):
    """Delete an ingress"""
    result = subprocess.run(
        ["kubectl", "delete", "ingress", name, "-n", NAMESPACE],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"  ✓ Deleted ingress: {name}")
        return True
    else:
        print(f"  ✗ Failed to delete ingress {name}: {result.stderr}")
        return False


def delete_secret(name):
    """Delete a secret"""
    result = subprocess.run(
        ["kubectl", "delete", "secret", name, "-n", NAMESPACE],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"  ✓ Deleted secret: {name}")
        return True
    else:
        print(f"  ✗ Failed to delete secret {name}: {result.stderr}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Cleanup orphaned K8s resources")
    parser.add_argument(
        "--yes", "-y", action="store_true", help="Auto-confirm deletion"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Orphaned Resource Cleanup")
    print("=" * 60)
    print(f"Namespace: {NAMESPACE}\n")

    # Get current resources
    print("📋 Fetching resources...")
    deployments = get_deployments()
    services = get_services()
    ingresses = get_ingresses()
    secrets = get_secrets()

    print(f"  Found {len(deployments)} deployments")
    print(f"  Found {len(services)} services")
    print(f"  Found {len(ingresses)} ingresses")
    print(f"  Found {len(secrets)} credential secrets\n")

    # Find orphaned resources
    orphaned_services = services - deployments - set(PROTECTED_SERVICES)
    orphaned_ingresses = ingresses - deployments - set(PROTECTED_INGRESSES)

    # Secrets end with -credentials, so remove that suffix to match deployment names
    deployment_credential_names = {f"{d}-credentials" for d in deployments}
    orphaned_secrets = secrets - deployment_credential_names

    print(f"🔍 Analysis:")
    print(f"  Orphaned services: {len(orphaned_services)}")
    print(f"  Orphaned ingresses: {len(orphaned_ingresses)}")
    print(f"  Orphaned secrets: {len(orphaned_secrets)}\n")

    if not orphaned_services and not orphaned_ingresses and not orphaned_secrets:
        print("✨ No orphaned resources found. Everything is clean!")
        return 0

    # Show what will be deleted
    if orphaned_services:
        print("Services to delete:")
        for svc in sorted(orphaned_services):
            print(f"  - {svc}")
        print()

    if orphaned_ingresses:
        print("Ingresses to delete:")
        for ing in sorted(orphaned_ingresses):
            print(f"  - {ing}")
        print()

    if orphaned_secrets:
        print("Secrets to delete:")
        for sec in sorted(orphaned_secrets):
            print(f"  - {sec}")
        print()

    # Confirm
    if not args.yes:
        try:
            confirm = input("Proceed with deletion? [y/N]: ").strip().lower()
            if confirm != "y":
                print("❌ Cancelled")
                return 1
        except (EOFError, KeyboardInterrupt):
            print("\n❌ Cancelled")
            return 1

    print("\n🗑️  Deleting orphaned resources...\n")

    deleted_services = 0
    deleted_ingresses = 0
    deleted_secrets = 0

    # Delete services
    for svc in sorted(orphaned_services):
        if delete_service(svc):
            deleted_services += 1

    # Delete ingresses
    for ing in sorted(orphaned_ingresses):
        if delete_ingress(ing):
            deleted_ingresses += 1

    # Delete secrets
    for sec in sorted(orphaned_secrets):
        if delete_secret(sec):
            deleted_secrets += 1

    print("\n" + "=" * 60)
    print("✅ Cleanup Complete")
    print("=" * 60)
    print(f"Deleted {deleted_services} services")
    print(f"Deleted {deleted_ingresses} ingresses")
    print(f"Deleted {deleted_secrets} secrets")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
