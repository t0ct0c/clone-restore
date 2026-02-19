#!/usr/bin/env python3
"""
Bulk Clone Creator - Creates 20 WordPress clones for load testing

Usage: python3 bulk-create-clones.py

Requirements:
  pip install requests
"""

import requests
import json
import time
from datetime import datetime

# Configuration
API_BASE = "https://clones.betaweb.ai/api"
SOURCE_URL = "https://betaweb.ai"
SOURCE_USERNAME = "Charles@toctoc.com.au"
SOURCE_PASSWORD = "6(4b`Nde1i_D"
CLONE_COUNT = 20
TTL_MINUTES = 60  # 1 hour TTL

def create_clone(clone_id: str) -> dict:
    """Create a single WordPress clone"""
    url = f"{API_BASE}/clone"
    
    payload = {
        "source": {
            "url": SOURCE_URL,
            "username": SOURCE_USERNAME,
            "password": SOURCE_PASSWORD
        },
        "auto_provision": True,
        "ttl_minutes": TTL_MINUTES
    }
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        return {
            "success": True,
            "clone_id": clone_id,
            "response": response.text,
            "timestamp": datetime.now().isoformat()
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "clone_id": clone_id,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

def main():
    print("=" * 70)
    print(f"BULK CLONE CREATION - {CLONE_COUNT} clones")
    print("=" * 70)
    print(f"Source: {SOURCE_URL}")
    print(f"TTL: {TTL_MINUTES} minutes")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 70)
    
    results = []
    
    for i in range(1, CLONE_COUNT + 1):
        clone_id = f"bulk-test-{i:03d}"
        print(f"[{i:2d}/{CLONE_COUNT}] Creating {clone_id}...", end=" ")
        
        result = create_clone(clone_id)
        results.append(result)
        
        if result["success"]:
            print("OK")
        else:
            print(f"FAILED: {result['error']}")
        
        # Small delay to avoid overwhelming the API
        time.sleep(0.5)
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    successful = sum(1 for r in results if r["success"])
    failed = CLONE_COUNT - successful
    
    print(f"Successful: {successful}/{CLONE_COUNT}")
    print(f"Failed: {failed}/{CLONE_COUNT}")
    print(f"Completed: {datetime.now().isoformat()}")
    
    if failed > 0:
        print("\nFailed clones:")
        for r in results:
            if not r["success"]:
                print(f"  - {r['clone_id']}: {r['error']}")
    
    print("=" * 70)
    
    # Save results to file
    output_file = f"bulk-clone-results-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\nResults saved to: {output_file}")
    print(f"\nAll clones will auto-delete after {TTL_MINUTES} minutes.")

if __name__ == "__main__":
    main()
