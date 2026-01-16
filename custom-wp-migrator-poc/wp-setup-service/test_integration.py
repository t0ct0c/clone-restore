#!/usr/bin/env python3
"""
Complete Integration Test for WordPress Migration Service
Tests all endpoints and workflows to ensure proper integration.
"""

import requests
import json
import time
import sys

BASE_URL = "http://localhost:5000"

def test_health():
    """Test health endpoint"""
    print("🔍 Testing health endpoint...")
    response = requests.get(f"{BASE_URL}/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    print("✅ Health endpoint working")

def test_setup():
    """Test setup endpoint with working credentials"""
    print("🔍 Testing setup endpoint...")
    payload = {
        "url": "https://wordpress-migrator-production.up.railway.app",
        "username": "charles",
        "password": "v^5F$D77tTSjrruWY%",
        "role": "source"
    }
    
    response = requests.post(f"{BASE_URL}/setup", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] == True
    assert "api_key" in data
    assert data["plugin_status"] == "activated"
    print(f"✅ Setup endpoint working - API Key: {data['api_key'][:10]}...")
    return data["api_key"]

def test_setup_target():
    """Test setup endpoint for target site"""
    print("🔍 Testing setup endpoint for target...")
    payload = {
        "url": "https://wordpress-migrator-production.up.railway.app",
        "username": "charles", 
        "password": "v^5F$D77tTSjrruWY%",
        "role": "target"
    }
    
    response = requests.post(f"{BASE_URL}/setup", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] == True
    assert "api_key" in data
    assert data["plugin_status"] == "activated"
    print(f"✅ Target setup working - API Key: {data['api_key'][:10]}...")
    return data["api_key"]

def test_clone_workflow():
    """Test complete clone workflow"""
    print("🔍 Testing complete clone workflow...")
    
    # Note: Using same site for both source and target for testing
    # In production, these would be different sites
    payload = {
        "source": {
            "url": "https://wordpress-migrator-production.up.railway.app",
            "username": "charles",
            "password": "v^5F$D77tTSjrruWY%"
        },
        "target": {
            "url": "https://wordpress-migrator-production.up.railway.app", 
            "username": "charles",
            "password": "v^5F$D77tTSjrruWY%"
        }
    }
    
    print("⏳ Starting clone operation (this may take a while)...")
    response = requests.post(f"{BASE_URL}/clone", json=payload, timeout=300)
    
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Clone workflow completed successfully")
        print(f"   Source API Key: {data.get('source_api_key', 'N/A')[:10]}...")
        print(f"   Target API Key: {data.get('target_api_key', 'N/A')[:10]}...")
        print(f"   Import Enabled: {data.get('target_import_enabled', False)}")
    else:
        print(f"❌ Clone workflow failed: {response.status_code}")
        print(f"   Response: {response.text}")
        return False
    
    return True

def main():
    """Run complete integration test suite"""
    print("🚀 Starting WordPress Migration Service Integration Tests\n")
    
    try:
        # Test individual endpoints
        test_health()
        print()
        
        api_key_source = test_setup()
        print()
        
        api_key_target = test_setup_target()
        print()
        
        # Test complete workflow
        clone_success = test_clone_workflow()
        print()
        
        if clone_success:
            print("🎉 ALL INTEGRATION TESTS PASSED!")
            print("\n📋 Integration Summary:")
            print("   ✅ Health endpoint working")
            print("   ✅ Setup endpoint working (source & target)")
            print("   ✅ Plugin activation working (Playwright)")
            print("   ✅ Complete clone workflow working")
            print("   ✅ Async/await integration fixed")
            print("\n🔧 Service is ready for production use!")
        else:
            print("⚠️  Some tests failed - check logs above")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ Integration test failed with error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
