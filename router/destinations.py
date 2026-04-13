"""
Webhook posting for Teams and Slack.

Posts formatted alert cards to Microsoft Teams (Adaptive Card)
or Slack (Block Kit) incoming webhooks.
"""

from datetime import datetime
import requests


def _relevance_color(score: int) -> str:
    """Return Adaptive Card color keyword based on relevance score."""
    if score >= 8:
        return "Good"       # green
    elif score >= 5:
        return "Warning"    # amber
    elif score >= 1:
        return "Attention"  # red
    return "Default"


def _relevance_emoji(score: int) -> str:
    """Return an emoji indicator for Slack based on relevance score."""
    if score >= 8:
        return "\u2705"     # green tick
    elif score >= 5:
        return "\u26a0\ufe0f"  # warning
    elif score >= 1:
        return "\ud83d\udfe0"  # orange circle
    return "\u2b1b"         # black square


def _format_value(value: int) -> str:
    """Format a GBP value for display. Returns 'Not published' if 0."""
    if not value or value == 0:
        return "Not published"
    return f"\u00a3{value:,.0f}"


def _format_date(date_str) -> str:
    """Format an ISO date for display. Returns 'Not specified' if None."""
    if not date_str:
        return "Not specified"
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y")
    except (ValueError, AttributeError):
        return date_str


def _build_openopps_url(record: dict) -> str:
    """Build a direct link to the record on Open Opportunities."""
    ocid = record.get("ocid", "")
    tags = record.get("release_tags", "tender").lower()
    # Normalise tag to the base type
    if "award" in tags:
        tag = "award"
    elif "planning" in tags:
        tag = "planning"
    else:
        tag = "tender"
    if ocid:
        return f"https://app.openopps.com/search/details?tag={tag}&ocid={ocid}"
    return "https://app.openopps.com/search"


def _get_date_fields(record: dict) -> tuple[str, str]:
    """
    Select the right date label and value based on release_tags.

    Returns:
        (date_label, date_value) tuple
    """
    tags = record.get("release_tags", "")

    if "award" in tags.lower():
        start = _format_date(record.get("award_start_date_first"))
        end = _format_date(record.get("award_end_date_first"))
        if start != "Not specified" and end != "Not specified":
            return "Contract period", f"{start} to {end}"
        return "Contract period", start

    if "planning" in tags.lower():
        start = record.get("start_date") or record.get("date_created")
        return "Earliest start", _format_date(start)

    # Default: tender or anything else
    return "Closing date", _format_date(record.get("closing_date"))


def post_to_teams(webhook_url: str, record: dict, matched_rule_name: str,
                  summary: str, reason: str, relevance: int = 0) -> bool:
    """
    Post Adaptive Card to Teams webhook.

    Args:
        webhook_url: Teams incoming webhook URL
        record: Procurement record dict
        matched_rule_name: Name of the matched routing rule
        summary: LLM-generated summary
        reason: LLM-generated reason for match

    Returns:
        True on success, False on failure. Never raises.
    """
    value_display = _format_value(record.get("tender_gbp_value", 0))
    date_label, date_value = _get_date_fields(record)
    release_date = _format_date(record.get("release_date"))

    adaptive_card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "ColumnSet",
                "columns": [
                    {
                        "type": "Column",
                        "width": "auto",
                        "items": [
                            {
                                "type": "Image",
                                "url": "https://openopps-marketing-static.s3.eu-west-2.amazonaws.com/68a13074-90c8-4269-84bc-78cac7a04fcb.png",
                                "size": "Small",
                                "height": "24px",
                            }
                        ],
                        "verticalContentAlignment": "Center",
                    },
                    {
                        "type": "Column",
                        "width": "stretch",
                        "items": [
                            {
                                "type": "TextBlock",
                                "text": "Open Opportunities Alert",
                                "weight": "Bolder",
                                "size": "Medium",
                                "color": "Accent",
                            }
                        ],
                        "verticalContentAlignment": "Center",
                    },
                ],
            },
            {
                "type": "TextBlock",
                "text": record.get("tender_title", "Untitled"),
                "weight": "Bolder",
                "size": "Large",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Buyer", "value": record.get("buyer_name", "N/A")},
                    {"title": "Region", "value": f"{record.get('buyer_address_region', 'N/A')}, {record.get('buyer_address_country_name', 'N/A')}"},
                    {"title": "Document type", "value": record.get("release_tags", "N/A")},
                    {"title": "Status", "value": record.get("tag_status", "N/A")},
                    {"title": "Estimated value (GBP)", "value": value_display},
                    {"title": date_label, "value": date_value},
                    {"title": "Published", "value": release_date},
                    {"title": "Matched rule", "value": matched_rule_name},
                    {"title": "Why matched", "value": reason},
                ],
            },
            {
                "type": "ColumnSet",
                "separator": True,
                "columns": [
                    {
                        "type": "Column",
                        "width": "auto",
                        "items": [
                            {
                                "type": "TextBlock",
                                "text": f"Relevance: {relevance}/10",
                                "weight": "Bolder",
                                "size": "Medium",
                                "color": _relevance_color(relevance),
                            }
                        ],
                    },
                    {
                        "type": "Column",
                        "width": "stretch",
                        "items": [
                            {
                                "type": "TextBlock",
                                "text": "\u2588" * relevance + "\u2591" * (10 - relevance),
                                "size": "Medium",
                                "color": _relevance_color(relevance),
                            }
                        ],
                        "verticalContentAlignment": "Center",
                    },
                ],
            },
            {
                "type": "TextBlock",
                "text": "Summary",
                "weight": "Bolder",
            },
            {
                "type": "TextBlock",
                "text": summary,
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": "Powered by [Open Opportunities](https://openopps.com) · Data from 800+ sources across 180+ countries",
                "size": "Small",
                "isSubtle": True,
                "wrap": True,
                "separator": True,
            },
        ],
        "actions": [
            {
                "type": "Action.OpenUrl",
                "title": "View original notice",
                "url": record.get("tender_url", ""),
            },
            {
                "type": "Action.OpenUrl",
                "title": "View on Open Opportunities",
                "url": _build_openopps_url(record),
            },
        ],
    }

    # Power Automate Workflows webhooks use a different format
    # than the older Office 365 Connectors
    is_workflows = "powerautomate" in webhook_url or "logic.azure" in webhook_url
    if is_workflows:
        card = {
            "type": "AdaptiveCard",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": adaptive_card,
                }
            ],
        }
    else:
        card = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": adaptive_card,
                }
            ],
        }

    try:
        response = requests.post(webhook_url, json=card, timeout=30)
        if response.status_code in (200, 202):
            return True
        print(f"[ERROR] Teams webhook failed (HTTP {response.status_code}): {response.text}")
        return False
    except requests.RequestException as e:
        print(f"[ERROR] Teams webhook network error: {e}")
        return False


def post_to_slack(webhook_url: str, record: dict, matched_rule_name: str,
                  summary: str, reason: str, relevance: int = 0) -> bool:
    """
    Post Block Kit message to Slack webhook.

    Args:
        webhook_url: Slack incoming webhook URL
        record: Procurement record dict
        matched_rule_name: Name of the matched routing rule
        summary: LLM-generated summary
        reason: LLM-generated reason for match

    Returns:
        True on success, False on failure. Never raises.
    """
    value_display = _format_value(record.get("tender_gbp_value", 0))
    date_label, date_value = _get_date_fields(record)

    message = {
        "blocks": [
            {
                "type": "context",
                "elements": [
                    {
                        "type": "image",
                        "image_url": "https://openopps-marketing-static.s3.eu-west-2.amazonaws.com/68a13074-90c8-4269-84bc-78cac7a04fcb.png",
                        "alt_text": "Open Opportunities",
                    },
                    {
                        "type": "mrkdwn",
                        "text": "*Open Opportunities Alert*",
                    },
                ],
            },
            {
                "type": "header",
                "text": {"type": "plain_text", "text": record.get("tender_title", "Untitled")},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Buyer*\n{record.get('buyer_name', 'N/A')}"},
                    {"type": "mrkdwn", "text": f"*Region*\n{record.get('buyer_address_region', 'N/A')}"},
                    {"type": "mrkdwn", "text": f"*Type*\n{record.get('release_tags', 'N/A')}"},
                    {"type": "mrkdwn", "text": f"*Value*\n{value_display}"},
                    {"type": "mrkdwn", "text": f"*{date_label}*\n{date_value}"},
                    {"type": "mrkdwn", "text": f"*Matched rule*\n{matched_rule_name}"},
                    {"type": "mrkdwn", "text": f"*Relevance*\n{_relevance_emoji(relevance)} {relevance}/10"},
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Summary*\n{summary}",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View original notice"},
                        "url": record.get("tender_url", ""),
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View on Open Opportunities"},
                        "url": _build_openopps_url(record),
                    },
                ],
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Powered by <https://openopps.com|Open Opportunities> · Data from 800+ sources across 180+ countries",
                    },
                ],
            },
            {"type": "divider"},
        ],
    }

    try:
        response = requests.post(webhook_url, json=message, timeout=30)
        if response.status_code == 200:
            return True
        print(f"[ERROR] Slack webhook failed (HTTP {response.status_code}): {response.text}")
        return False
    except requests.RequestException as e:
        print(f"[ERROR] Slack webhook network error: {e}")
        return False


def post_alert(destination: dict, record: dict, matched_rule_name: str,
               summary: str, reason: str, relevance: int = 0) -> bool:
    """
    Route to correct poster based on destination type.

    Args:
        destination: Dict with keys: name, type, webhook
        record: Procurement record dict
        matched_rule_name: Name of the matched routing rule
        summary: LLM-generated summary
        reason: LLM-generated reason for match
        relevance: Relevance score 0-10

    Returns:
        True on success, False on failure.
    """
    dest_type = destination.get("type", "").lower()
    webhook_url = destination.get("webhook", "")

    if dest_type == "teams":
        return post_to_teams(webhook_url, record, matched_rule_name, summary, reason, relevance)
    elif dest_type == "slack":
        return post_to_slack(webhook_url, record, matched_rule_name, summary, reason, relevance)
    else:
        print(f"[ERROR] Unknown destination type: {dest_type}")
        return False
