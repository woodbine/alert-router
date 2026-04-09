# Open Opportunities Alert Router

Fetch today's government procurement opportunities, classify them with an LLM against your plain-English rules, and post matches to Microsoft Teams or Slack.

## What you need

- **Open Opportunities API credentials** - [Expert tier](https://openopps.com/expert)
- **Google Gemini API key** - [Get one at aistudio.google.com](https://aistudio.google.com/apikey)
- **A Microsoft Teams or Slack webhook URL** (see setup instructions below)

## Install

```bash
git clone https://github.com/openopps/alert-router
cd alert-router
pip install -r requirements.txt
```

## Configure

```bash
cp config.yaml.example config.yaml
```

Open `config.yaml` and fill in:

1. Your Spend Network API credentials (email + password)
2. Your Gemini API key
3. Your webhook URLs
4. Your routing rules (plain English descriptions of what each channel should receive)

## Run

```bash
python run.py                              # live run
python run.py --dry-run                    # classify but don't post
python run.py --limit 5                    # fetch only 5 records
python run.py --lookback 7                 # look back 7 days
python run.py --config /path/to/config.yaml  # custom config path
```

### Example dry-run output

```
[DRY RUN] Would post to: cyber-consulting (Teams)
  Title:   Cyber security operations centre managed service
  Buyer:   Home Office
  Value:   £2,400,000
  Rule:    cyber-consulting
  Summary: The Home Office is seeking a managed SOC provider for 24/7
           monitoring, incident response, and threat intelligence across
           its digital estate. Contract valued at £2.4M over 3 years.
```

### Run summary

Every run prints a summary:

```
--- Run complete ---
Records fetched:    247
Already processed:  12
Classified:         235
Matched:            18
Posted:             18
Unmatched:          217
Errors:             0
Duration:           43s
```

## Automate (run every morning at 7am)

```bash
crontab -e
```

Add this line:

```
0 7 * * * cd /path/to/alert-router && python run.py >> logs/run.log 2>&1
```

Create the logs directory first: `mkdir -p logs`

## How to get a Teams webhook URL

1. In Microsoft Teams, go to the channel where you want alerts
2. Click the **...** menu next to the channel name
3. Select **Connectors** (or **Workflows** in newer Teams)
4. Search for **Incoming Webhook**
5. Click **Configure**, give it a name like "Procurement Alerts"
6. Copy the webhook URL - paste it into your `config.yaml`

## How to get a Slack webhook URL

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **Create New App** > **From scratch**
3. Name it "Procurement Alerts", select your workspace
4. Go to **Incoming Webhooks** > toggle it **On**
5. Click **Add New Webhook to Workspace**
6. Select the channel for alerts
7. Copy the webhook URL - paste it into your `config.yaml`

## Writing effective routing rules

The quality of your routing rules determines the quality of your matches. Here are examples of good rules:

### Match by subject matter (specific)
```yaml
- description: >
    All cyber security consulting, penetration testing, SOC services,
    security architecture, threat intelligence, and red team exercises
  destination: cyber-team
```

### Match by buyer geography (include all relevant names)
```yaml
- description: >
    Any buying organisation that is a local authority, council, or combined
    authority in the South East of England including London, Kent, Surrey,
    Essex, Sussex, and Hampshire
  destination: south-east-bd
```

### Match by buyer type (name specific organisations)
```yaml
- description: >
    Any opportunity from a central government department, ministry, agency,
    or executive non-departmental public body, including the Home Office,
    NHS England, HMRC, MoD, and similar
  destination: central-gov
```

### Match by value threshold
```yaml
- description: >
    Any IT services or software development contract worth more than
    £500,000 from any UK public sector buyer
  destination: large-it-deals
```

### Match by sector and geography combined
```yaml
- description: >
    Healthcare equipment, medical devices, or pharmaceutical procurement
    from NHS trusts, clinical commissioning groups, or integrated care
    boards in the North West of England
  destination: nw-health
```

**Tips:**
- Be specific - include synonyms, alternative names, and examples
- Use plain English geography (not just ISO codes)
- Name specific organisations when matching by buyer type
- Include related terms (e.g., "cyber security, information security, infosec")
- Test with `--dry-run` to refine your rules before going live

## How it works

```
┌──────────────────┐     ┌──────────────┐     ┌──────────────┐
│ Spend Network    │────>│   Gemini      │────>│ Teams/Slack  │
│ Procurement API  │     │   (classify)  │     │  (webhooks)  │
└──────────────────┘     └──────────────┘     └──────────────┘
  Fetch daily records     Match against         Post formatted
  with your filters       routing rules         alert cards
```

1. **Fetch** - Queries the Spend Network API for today's opportunities matching your country, value, and document type filters
2. **Deduplicate** - Skips records that were already posted in previous runs
3. **Classify** - Sends each record to Gemini with your routing rules; the LLM identifies which rules match and writes a plain-English summary
4. **Route** - Posts formatted cards to the matched Teams or Slack channels

## Don't want to run this yourself?

This script demonstrates what's possible with the Open Opportunities API. If you'd rather have managed alerts without running code:

**[Open Opportunities Expert](https://openopps.com/expert)** includes API access, daily alerts, and more - so your team can focus on winning contracts, not maintaining scripts.

## License

MIT
