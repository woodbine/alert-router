"""
Fetch procurement records from the Spend Network API.

Handles pagination and query construction based on config parameters.
"""

from datetime import datetime, timedelta, timezone
import requests

# API limits
MAX_RECORDS_PER_PAGE = 100
MAX_OFFSET = 9900


def fetch_records(token: str, config: dict) -> list[dict]:
    """
    Fetch all matching records using pagination.

    Args:
        token: Bearer token from authentication
        config: Search configuration dict with keys:
            - countries: list of ISO alpha-2 codes
            - contract_types: list of release_tags to include
            - lookback_days: how many days back to query
            - limit: records per page (max 100)
            - min_value_gbp: minimum contract value (0 = no minimum)

    Returns:
        Flat list of all record dicts across all pages.
    """
    search = config.get("search", {})
    api_url = config.get("spend_network", {}).get("api_url", "https://api.spendnetwork.cloud")
    search_endpoint = f"{api_url}/api/v3/notices_summary/read_summary_records"
    lookback_days = search.get("lookback_days", 2)
    limit = min(search.get("limit", 100), MAX_RECORDS_PER_PAGE)
    countries = search.get("countries", ["GB"])
    contract_types = search.get("contract_types", ["tender"])
    min_value = search.get("min_value_gbp", 0)

    # Calculate the lookback date
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    all_records = []
    offset = 0

    while offset <= MAX_OFFSET:
        # Build request body
        body = {
            "release_date__gte": since_str,
            "release_tags__is": contract_types,
            "buyer_address_country_code__is": countries,
            "tag_status__is": "open",
            "sort_by": "release_date",
            "date_direction": "desc",
            "offset": offset,
            "limit": limit,
        }

        # Only include value filter if > 0
        if min_value > 0:
            body["value__gte"] = min_value

        page_num = (offset // limit) + 1

        try:
            response = requests.post(
                search_endpoint,
                json=body,
                headers=headers,
                timeout=60,
            )
        except requests.RequestException as e:
            print(f"[ERROR] Network error fetching page {page_num}: {e}")
            break

        if response.status_code != 200:
            print(f"[ERROR] API error on page {page_num} (HTTP {response.status_code})")
            print(f"[ERROR] Response: {response.text}")
            break

        data = response.json()
        results = data.get("results", [])
        all_records.extend(results)

        print(f"  Page {page_num}: {len(results)} records", flush=True)

        # Stop if this was the last page
        if len(results) < limit:
            break

        offset += limit

    return all_records
