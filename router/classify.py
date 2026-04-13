"""
LLM-based record classification.

Classifies procurement records against user-defined routing rules
using Google Gemini with structured JSON output.
"""

import json
from google import genai
from google.genai import types


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


def _build_relevance_gate_text(config: dict) -> str:
    """
    Build the relevance gate section for the prompt, if configured.

    Returns empty string if no gate is configured.
    """
    gate = config.get("relevance_gate")
    if not gate:
        return ""

    return f"""## Relevance Gate (MANDATORY FIRST CHECK)
Before evaluating ANY routing rules, you must first determine whether this
opportunity passes the relevance gate below. If it does NOT pass, set
matched_rules to an empty list and relevance to 0.

{gate.strip()}

If the opportunity does NOT pass this gate, return an empty matched_rules list.
Only proceed to evaluate routing rules if the gate is passed.

"""


def _build_prompt(record: dict, routing_rules: list,
                  relevance_gate_text: str = "") -> str:
    """Build the full classification prompt for a single record."""
    routing_rules_text = _build_routing_rules_text(routing_rules)
    cpv_aug_formatted = _format_cpv_aug_data(record)

    # Format publisher-supplied CPV codes
    cpv_codes = ", ".join(record.get("cpv_codes") or []) or "None"
    cpv_names = ", ".join(record.get("cpv_names") or []) or "None"

    return f"""You are a procurement opportunity classification assistant. Your job is to read
a tender or planning notice and decide which of the routing rules below it matches.

{relevance_gate_text}## Routing Rules
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
1. If a relevance gate is defined above, check it FIRST. If the record fails
   the gate, return an empty matched_rules list and relevance 0.
2. Review all routing rules carefully.
3. Identify ALL rules this record matches. There may be more than one.
4. Use the CPV relevance scores to calibrate confidence. Do not match a rule
   based solely on a low-scoring (below 8) augmented code when the title and
   description do not support it.
5. For each matching rule, provide the rule label (the destination name) exactly
   as it appears in the routing rules.
6. Write a 2-3 sentence plain English summary of the opportunity suitable for
   a business development professional. Focus on what is being procured, who
   is buying it, and any notable value or timeline.
7. Score the relevance of this opportunity on a scale of 1-10 where:
   1-3 = marginal match, keyword appeared but core subject is different
   4-6 = partial match, some relevance but not a strong fit
   7-8 = good match, clearly relevant
   9-10 = excellent match, directly on topic
   If the record fails the relevance gate, score 0.

Return your response as JSON."""


# JSON schema for structured output
CLASSIFICATION_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "matched_rules": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(type=types.Type.STRING),
            description="List of matched destination names, or empty list if none match",
        ),
        "relevance": types.Schema(
            type=types.Type.INTEGER,
            description="Relevance score 0-10. 0 if gate failed, 1-3 marginal, 4-6 partial, 7-8 good, 9-10 excellent",
        ),
        "summary": types.Schema(
            type=types.Type.STRING,
            description="2-3 sentence plain English summary of the opportunity",
        ),
        "reason": types.Schema(
            type=types.Type.STRING,
            description="One sentence explaining which signals drove the classification decision",
        ),
    },
    required=["matched_rules", "relevance", "summary", "reason"],
)


def classify_record(record: dict, routing_rules: list, llm_config: dict,
                    config: dict = None) -> dict:
    """
    Classify a single record against routing rules using Google Gemini.

    Uses structured JSON output for reliable parsing.

    Args:
        record: A procurement record dict from the API.
        routing_rules: List of routing rule dicts with 'destination' and 'description'.
        llm_config: LLM configuration with 'api_key' and 'model'.
        config: Full config dict (optional, used for relevance_gate).

    Returns:
        {
            "matched_destinations": ["bd-south", "consulting"],
            "relevance": 8,
            "summary": "The Home Office is seeking...",
            "reason": "Strong CPV match for IT security services..."
        }

    On LLM failure: logs error, returns empty result. Never raises.
    """
    ocid = record.get("ocid", "unknown")

    try:
        relevance_gate_text = _build_relevance_gate_text(config or {})
        prompt = _build_prompt(record, routing_rules, relevance_gate_text)

        client = genai.Client(api_key=llm_config["api_key"])
        response = client.models.generate_content(
            model=llm_config.get("model", "gemini-2.0-flash"),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CLASSIFICATION_SCHEMA,
            ),
        )

        data = json.loads(response.text)

        return {
            "matched_destinations": data.get("matched_rules", []),
            "relevance": data.get("relevance", 0),
            "summary": data.get("summary", ""),
            "reason": data.get("reason", ""),
        }

    except Exception as e:
        print(f"[ERROR] LLM classification failed for {ocid}: {e}")
        return {
            "matched_destinations": [],
            "relevance": 0,
            "summary": "",
            "reason": "LLM error",
        }
