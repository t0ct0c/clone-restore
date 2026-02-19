#!/usr/bin/env python3
"""
Bulk Clone Deleter - Deletes WordPress clones created by bulk-create-clones.py

Usage:
  python3 delete-clones.py bulk-clone-results-20260219-123456.json
  python3 delete-clones.py --all  (deletes all bulk-test-* clones)
"""

import requests
import json
import sys
import re
from datetime import datetime

API_BASE = "https://clones.betaweb.ai/api"

def delete_clone(clone_id: str) -> dict:
    """Delete a single clone"""
    url = f"{API_BASE}/delete"
    payload = {"clone_id": clone_id}
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        return {
            "success": response.status_code == 200,
            "clone_id": clone_id,
            "status_code": response.status_code,
            "response": response.text[:100]
        }
    except Exception as e:
        return {
            "success": False,
            "clone_id": clone_id,
            "error": str(e)
        }

def extract_clone_ids_from_file(filepath: str) -> list:
    """Extract clone IDs from results file"""
    with open(filepath, "r") as f:
        data = json.load(f)
    return [r["clone_id"] for r in data if r.get("success")]

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 delete-clones.py <results-file.json>")
        print("  python3 delete-clones.py --all")
        sys.exit(1)
    
    clone_ids = []
    
    if sys.argv[1] == "--all":
        print("WARNING: This will delete ALL bulk-test-* clones!")
        confirm = input("Type 'yes' to confirm: ")
        if confirm.lower() != "yes":
            print("Aborted.")
            sys.exit(0)
        # Pattern match bulk-test-*
        clone_ids = [f"bulk-test-{i:03d}" for i in range(1, 101)]
        print(f"Will attempt to delete up to 100 bulk-test-* clones\n")
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
    
    print(f"Deleting {len(clone_ids)} clones...\n")
    
    results = []
    start = datetime.now()
    
    for i, clone_id in enumerate(clone_ids, 1):
        result = delete_clone(clone_id)
        results.append(result)
        
        status = "OK" if result["success"] else "FAILED"
        print(f"[{i:3d}/{len(clone_ids)}] {clone_id} - {status}")
    
    elapsed = (datetime.now() - start).total_seconds()
    successful = sum(1 for r in results if r["success"])
    
    print(f"\n{'='*50}")
    print(f"Deleted: {successful}/{len(clone_ids)}")
    print(f"Time: {elapsed:.1f}s")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()
