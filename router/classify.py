"""
LLM-based record classification.

Classifies procurement records against user-defined routing rules
using Google Gemini.
"""

from google import genai


def _format_cpv_aug_data(record: dict) -> str:
    """
    Format CPV augmented data into a readable string for the LLM.

    Each item is formatted as:
        Category name (CODE) - relevance score: X.XXXX

    Returns a fallback message if no augmented data is available.
    """
    cpv_aug = record.get("cpv_aug_data") or []

    if not cpv_aug:
        return "No augmented CPV data available for this record"

    lines = []
    for item in cpv_aug:
        name = item.get("cpv_aug_names", "Unknown")
        code = item.get("cpv_aug_codes", "N/A")
        score = item.get("relevance_score", 0)
        lines.append(f"{name} ({code}) - relevance score: {score:.4f}")

    return "\n".join(lines)


def _build_routing_rules_text(routing_rules: list) -> str:
    """
    Build the routing rules section for the classification prompt.

    Each rule is formatted as:
        Rule: {destination}
        Description: {description}
    """
    lines = []
    for rule in routing_rules:
        lines.append(f"Rule: {rule['destination']}")
        lines.append(f"Description: {rule['description'].strip()}")
        lines.append("")
    return "\n".join(lines)


def _build_prompt(record: dict, routing_rules: list) -> str:
    """Build the full classification prompt for a single record."""
    routing_rules_text = _build_routing_rules_text(routing_rules)
    cpv_aug_formatted = _format_cpv_aug_data(record)

    # Format publisher-supplied CPV codes
    cpv_codes = ", ".join(record.get("cpv_codes") or []) or "None"
    cpv_names = ", ".join(record.get("cpv_names") or []) or "None"

    return f"""You are a procurement opportunity classification assistant. Your job is to read
a tender or planning notice and decide which of the routing rules below it matches.

## Routing Rules
{routing_rules_text}

## Tender Record

**Core fields**
- Title: {record.get("tender_title", "N/A")}
- Description: {record.get("tender_description", "N/A")}
- Document Type: {record.get("release_tags", "N/A")}
- Status: {record.get("tag_status", "N/A")}
- GBP Value: {record.get("tender_gbp_value", 0)}

**Buyer information**
- Buyer Name: {record.get("buyer_name", "N/A")}
- Buyer Country: {record.get("buyer_address_country_name", "N/A")}
- Buyer Region: {record.get("buyer_address_region", "N/A")}

**CPV classification - publisher supplied**
These codes were provided by the buyer themselves. They may be vague,
incomplete, or misclassified.
- CPV Codes: {cpv_codes}
- CPV Names: {cpv_names}

**CPV classification - Spend Network augmented (with relevance scores)**
These codes were independently assigned by Spend Network's classification system.
They are generally more reliable than publisher-supplied codes.
Relevance score guidance: above 12 = strong match, 8-12 = moderate match,
below 8 = weak or marginal match. Weight your classification accordingly.
Where publisher-supplied and augmented codes agree, confidence is highest.
Where they disagree, favour augmented codes with scores above 12.
{cpv_aug_formatted}

## Instructions
1. Review all routing rules carefully.
2. Identify ALL rules this record matches. There may be more than one.
3. Use the CPV relevance scores to calibrate confidence. Do not match a rule
   based solely on a low-scoring (below 8) augmented code when the title and
   description do not support it.
4. For each matching rule, provide the rule label (the destination name) exactly
   as it appears in the routing rules.
5. Write a 2-3 sentence plain English summary of the opportunity suitable for
   a business development professional. Focus on what is being procured, who
   is buying it, and any notable value or timeline.
6. Return your response in this EXACT format and nothing else:

MATCHED_RULES: [comma-separated list of matched destination names, or NONE]
SUMMARY: [your 2-3 sentence summary]
REASON: [one sentence explaining which signals drove the classification decision]

If no rules match, return MATCHED_RULES: NONE and still provide SUMMARY and REASON."""


def _parse_response(text: str) -> dict:
    """
    Parse the LLM response into structured data.

    Extracts matched_destinations, summary, and reason from the
    plain-text response. Handles malformed responses gracefully.
    """
    result = {
        "matched_destinations": [],
        "summary": "",
        "reason": "",
    }

    try:
        # Extract MATCHED_RULES
        if "MATCHED_RULES:" in text:
            rules_line = text.split("MATCHED_RULES:")[1].split("\n")[0].strip()
            if rules_line.upper() != "NONE" and rules_line:
                # Handle bracket-wrapped or plain comma-separated lists
                rules_line = rules_line.strip("[]")
                result["matched_destinations"] = [
                    r.strip() for r in rules_line.split(",") if r.strip()
                ]

        # Extract SUMMARY
        if "SUMMARY:" in text:
            summary_text = text.split("SUMMARY:")[1]
            if "REASON:" in summary_text:
                summary_text = summary_text.split("REASON:")[0]
            result["summary"] = summary_text.strip()

        # Extract REASON
        if "REASON:" in text:
            result["reason"] = text.split("REASON:")[1].strip()

    except (IndexError, AttributeError):
        # Malformed response - return empty result
        pass

    return result


def classify_record(record: dict, routing_rules: list, llm_config: dict) -> dict:
    """
    Classify a single record against routing rules using Google Gemini.

    Args:
        record: A procurement record dict from the API.
        routing_rules: List of routing rule dicts with 'destination' and 'description'.
        llm_config: LLM configuration with 'api_key' and 'model'.

    Returns:
        {
            "matched_destinations": ["cyber-consulting", "jane-smith"],
            "summary": "The Home Office is seeking...",
            "reason": "Strong CPV match for IT security services..."
        }

    On LLM failure: logs error, returns empty result. Never raises.
    """
    ocid = record.get("ocid", "unknown")

    try:
        prompt = _build_prompt(record, routing_rules)

        client = genai.Client(api_key=llm_config["api_key"])
        response = client.models.generate_content(
            model=llm_config.get("model", "gemini-2.0-flash"),
            contents=prompt,
        )

        response_text = response.text
        return _parse_response(response_text)

    except Exception as e:
        print(f"[ERROR] LLM classification failed for {ocid}: {e}")
        return {
            "matched_destinations": [],
            "summary": "",
            "reason": "LLM error",
        }
