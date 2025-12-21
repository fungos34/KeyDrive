#!/usr/bin/env python3
"""
Test Update Endpoints

Simple script to test the Django update endpoints.
"""

import json
import urllib.request
import urllib.error

def test_endpoint(url, description):
    print(f"\nTesting {description}: {url}")
    try:
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode())
            print(f"✅ Status: {response.status}")
            print(f"Response: {json.dumps(data, indent=2)}")
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP Error {e.code}: {e.reason}")
    except Exception as e:
        print(f"❌ Error: {e}")

def main():
    base_url = 'http://localhost:8001/api'

    # Test endpoints
    test_endpoint(f'{base_url}/update/latest/', 'Latest Update Info')
    test_endpoint(f'{base_url}/update/check/0.9.0/', 'Update Check (older version)')
    test_endpoint(f'{base_url}/update/check/1.0.0/', 'Update Check (current version)')
    test_endpoint(f'{base_url}/update/history/', 'Update History')

    # Test download endpoints (will fail without package file)
    test_endpoint(f'{base_url}/update/download/latest/', 'Download Latest (expected to fail)')
    test_endpoint(f'{base_url}/update/download/1.0.0/', 'Download Version (expected to fail)')

if __name__ == '__main__':
    main()