#!/usr/bin/env python3
"""
Open Opportunities Alert Router

Fetches today's procurement opportunities, classifies them against
routing rules using an LLM, and posts matches to Teams or Slack.

Usage:
    python run.py                         # live run
    python run.py --dry-run               # classify but don't post
    python run.py --limit 5               # fetch only 5 records
    python run.py --config /path/to.yaml  # custom config path
"""

import sys
import time

import click
import yaml

from router.auth import get_token
from router.fetch import fetch_records
from router.dedupe import load_processed, is_processed, mark_processed
from router.classify import classify_record
from router.destinations import post_alert


def load_config(config_path: str) -> dict:
    """
    Load and validate the YAML configuration file.

    Validates that all required fields are present and correctly typed.
    Exits with a clear error message if anything is wrong.
    """
    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"[ERROR] Config file not found: {config_path}")
        print(f"[ERROR] Copy config.yaml.example to config.yaml and fill in your values.")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"[ERROR] Invalid YAML in {config_path}: {e}")
        sys.exit(1)

    # Validate required sections
    required_sections = ["spend_network", "llm", "search", "destinations", "routing_rules"]
    for section in required_sections:
        if section not in config:
            print(f"[ERROR] Missing required config section: {section}")
            sys.exit(1)

    # Validate spend_network credentials
    sn = config["spend_network"]
    if not sn.get("username") or not sn.get("password"):
        print("[ERROR] spend_network.username and spend_network.password are required")
        sys.exit(1)

    # Validate LLM config
    llm = config["llm"]
    if not llm.get("api_key"):
        print("[ERROR] llm.api_key is required")
        sys.exit(1)

    # Validate destinations
    for i, dest in enumerate(config["destinations"]):
        if not dest.get("name") or not dest.get("type") or not dest.get("webhook"):
            print(f"[ERROR] Destination {i} missing name, type, or webhook")
            sys.exit(1)
        if dest["type"] not in ("teams", "slack"):
            print(f"[ERROR] Destination '{dest['name']}' has invalid type: {dest['type']} (must be 'teams' or 'slack')")
            sys.exit(1)

    # Validate routing rules
    dest_names = {d["name"] for d in config["destinations"]}
    for i, rule in enumerate(config["routing_rules"]):
        if not rule.get("description") or not rule.get("destination"):
            print(f"[ERROR] Routing rule {i} missing description or destination")
            sys.exit(1)
        if rule["destination"] not in dest_names:
            print(f"[ERROR] Routing rule '{rule['destination']}' references unknown destination")
            print(f"[ERROR] Available destinations: {', '.join(dest_names)}")
            sys.exit(1)

    return config


@click.command()
@click.option("--config", "config_path", default="config.yaml", help="Path to config file")
@click.option("--dry-run", is_flag=True, help="Classify but do not post to webhooks")
@click.option("--limit", type=int, default=None, help="Override config limit for testing")
@click.option("--lookback", type=int, default=None, help="Override config lookback_days")
def main(config_path: str, dry_run: bool, limit, lookback: int | None):
    """Open Opportunities Alert Router - fetch, classify, and route procurement opportunities."""

    start_time = time.time()

    # 1. Load and validate config
    config = load_config(config_path)

    # Apply CLI overrides
    if limit is not None:
        config["search"]["limit"] = limit
    if lookback is not None:
        config["search"]["lookback_days"] = lookback

    if dry_run:
        print("[DRY RUN] Classification only - no webhooks will be called\n")

    # 2. Authenticate
    print("[AUTH] Authenticating with Spend Network API...")
    api_url = config["spend_network"].get("api_url", "https://api.spendnetwork.cloud")
    token = get_token(
        config["spend_network"]["username"],
        config["spend_network"]["password"],
        api_url=api_url,
    )
    print("[AUTH] Authenticated successfully\n")

    # 3. Fetch records
    print("[FETCH] Fetching procurement records...")
    records = fetch_records(token, config)
    print(f"[FETCH] Retrieved {len(records)} records\n")

    if not records:
        print("0 records matched your filters. Nothing to do.")
        sys.exit(0)

    # 4. Load deduplication state
    processed = load_processed()

    # Build destination lookup
    dest_lookup = {d["name"]: d for d in config["destinations"]}

    # Counters
    stats = {
        "fetched": len(records),
        "already_processed": 0,
        "classified": 0,
        "matched": 0,
        "posted": 0,
        "unmatched": 0,
        "errors": 0,
    }

    # 5. Classify and route each record
    for i, record in enumerate(records, 1):
        ocid = record.get("ocid", "unknown")

        # 5a. Skip if already processed
        if is_processed(ocid, processed):
            stats["already_processed"] += 1
            continue

        # 5b. Classify
        title = record.get("tender_title", "Untitled")[:80]
        print(f"[{i}/{len(records)}] Classifying: {title}...")

        classification = classify_record(
            record,
            config["routing_rules"],
            config["llm"],
        )
        stats["classified"] += 1

        matched = classification["matched_destinations"]
        summary = classification["summary"]
        reason = classification["reason"]

        if not matched:
            stats["unmatched"] += 1
            continue

        stats["matched"] += 1

        # 5c. Post to each matched destination
        any_success = False
        for dest_name in matched:
            destination = dest_lookup.get(dest_name)
            if not destination:
                print(f"  [WARN] Matched destination '{dest_name}' not found in config")
                continue

            if dry_run:
                value = record.get("tender_gbp_value", 0)
                value_str = f"\u00a3{value:,.0f}" if value else "Not published"
                print(f"  [DRY RUN] Would post to: {dest_name} ({destination['type']})")
                print(f"    Title:   {record.get('tender_title', 'N/A')}")
                print(f"    Buyer:   {record.get('buyer_name', 'N/A')}")
                print(f"    Value:   {value_str}")
                print(f"    Rule:    {dest_name}")
                print(f"    Summary: {summary}")
                print()
                any_success = True
            else:
                success = post_alert(destination, record, dest_name, summary, reason)
                if success:
                    print(f"  [OK] Posted to {dest_name}")
                    any_success = True
                else:
                    stats["errors"] += 1

        # 5d. Mark as processed if any post succeeded
        if any_success and not dry_run:
            mark_processed(ocid)

    # 6. Print run summary
    duration = int(time.time() - start_time)
    print(f"""
--- Run complete ---
Records fetched:    {stats['fetched']}
Already processed:  {stats['already_processed']}
Classified:         {stats['classified']}
Matched:            {stats['matched']}
Posted:             {stats['posted'] if not dry_run else 'N/A (dry run)'}
Unmatched:          {stats['unmatched']}
Errors:             {stats['errors']}
Duration:           {duration}s""")


if __name__ == "__main__":
    main()
