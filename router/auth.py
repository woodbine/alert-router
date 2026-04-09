"""
Spend Network API authentication.

Authenticates with the Spend Network API and returns a bearer token
for use in subsequent API calls.
"""

import sys
import requests


def get_token(username: str, password: str, api_url: str = "https://api.spendnetwork.cloud") -> str:
    """
    Authenticate with Spend Network API.

    Args:
        username: Spend Network login email
        password: Spend Network password
        api_url: Base URL for the Spend Network API

    Returns:
        Bearer token string.

    Raises:
        SystemExit with clear message on failure.
    """
    login_endpoint = f"{api_url}/api/v3/login/access-token"

    try:
        response = requests.post(
            login_endpoint,
            json={"username": username, "password": password},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"[ERROR] Network error during authentication: {e}")
        sys.exit(1)

    if response.status_code != 200:
        print(f"[ERROR] Authentication failed (HTTP {response.status_code})")
        print(f"[ERROR] Response: {response.text}")
        sys.exit(1)

    data = response.json()
    token = data.get("access_token")

    if not token:
        print(f"[ERROR] No access_token in response: {data}")
        sys.exit(1)

    return token
