"""
DNS TXT record stack-detection.

TXT records carry SPF/DKIM/DMARC entries and domain-verification tokens
from third-party services. The verification tokens are a free readout of
a company's SaaS stack: Google Workspace, Microsoft 365, Atlassian,
Stripe, Segment, Zendesk, HubSpot, Shopify, Notion, Cloudflare, etc. —
each uses a distinct token prefix. Combined with SPF include: lines
(which list every service authorized to send mail on the domain's
behalf), you get a solid read on what the company uses without touching
their website.

Uses Google's DNS-over-HTTPS JSON API (dns.google) — no local resolver
needed, no extra dependency. Cloudflare (1.1.1.1) is a fallback.

Usage:
    python3 -m supersearch.scrapers.dns_txt example.com
    python3 -m supersearch.scrapers.dns_txt example.com --raw
"""

import json
import re
import sys
from typing import Optional
from urllib.parse import urlparse

import requests


DEFAULT_TIMEOUT = 10
DOH_ENDPOINTS = [
    "https://dns.google/resolve",
    "https://cloudflare-dns.com/dns-query",
]

# Mapping of distinctive TXT-token substrings to the service they verify for.
# Conservative — only matches that are distinctive enough to avoid false positives.
TOKEN_SIGNATURES = [
    ("google-site-verification=", "Google Search Console / Workspace"),
    ("MS=ms", "Microsoft 365 / Azure AD"),
    ("atlassian-domain-verification=", "Atlassian (Jira/Confluence)"),
    ("stripe-verification=", "Stripe"),
    ("adobe-idp-site-verification=", "Adobe"),
    ("amazonses:", "Amazon SES"),
    ("apple-domain-verification=", "Apple Business"),
    ("cisco-ci-domain-verification=", "Cisco"),
    ("docusign=", "DocuSign"),
    ("facebook-domain-verification=", "Facebook / Meta Business"),
    ("globalsign-domain-verification=", "GlobalSign"),
    ("have-i-been-pwned-verification=", "Have I Been Pwned"),
    ("logmein-verification-code=", "LogMeIn / GoTo"),
    ("mongodb-site-verification=", "MongoDB"),
    ("onetrust-domain-verification=", "OneTrust"),
    ("openai-domain-verification=", "OpenAI"),
    ("anthropic-domain-verification=", "Anthropic"),
    ("pardot", "Salesforce Pardot"),
    ("pinterest-site-verification=", "Pinterest"),
    ("segment-site-verification=", "Segment"),
    ("shopify-verification-code", "Shopify"),
    ("slack-domain-verification=", "Slack"),
    ("status-page-domain-verification=", "Statuspage (Atlassian)"),
    ("stripe-verification=", "Stripe"),
    ("tableau-domain-verification=", "Tableau"),
    ("webexdomainverification=", "Cisco Webex"),
    ("workplace-domain-verification=", "Meta Workplace"),
    ("yandex-verification:", "Yandex"),
    ("zendeskverification=", "Zendesk"),
    ("zoom_verify_", "Zoom"),
    ("hubspot", "HubSpot"),
    ("notion.so", "Notion"),
    ("loom-site-verification", "Loom"),
    ("miro-verification", "Miro"),
    ("intercom-domain-verification=", "Intercom"),
    ("asana-verification=", "Asana"),
    ("bugcrowd-verification=", "Bugcrowd"),
    ("hackerone-verification=", "HackerOne"),
    ("dropbox-domain-verification=", "Dropbox"),
    ("box-verification=", "Box"),
    ("brevo-code:", "Brevo (Sendinblue)"),
    ("mailchimp-domain-verification=", "Mailchimp"),
    ("klaviyo-site-verification=", "Klaviyo"),
    ("twilio-domain-verification=", "Twilio"),
    ("sendgrid.net", "SendGrid"),
    ("mailgun.org", "Mailgun"),
    ("_amazonses", "Amazon SES (DKIM)"),
    ("_acme-challenge", "Let's Encrypt / ACME"),
]

# SPF include: hints — maps a hostname fragment to a readable service label.
SPF_SIGNATURES = [
    ("_spf.google.com", "Google Workspace mail"),
    ("spf.protection.outlook.com", "Microsoft 365 mail"),
    ("amazonses.com", "Amazon SES mail"),
    ("mailgun.org", "Mailgun mail"),
    ("sendgrid.net", "SendGrid mail"),
    ("mailchimp", "Mailchimp mail"),
    ("zendesk.com", "Zendesk mail"),
    ("salesforce.com", "Salesforce mail"),
    ("intercom-mail.com", "Intercom mail"),
    ("hubspot", "HubSpot mail"),
    ("klaviyo", "Klaviyo mail"),
    ("stripe.com", "Stripe mail"),
    ("mktomail.com", "Marketo mail"),
    ("helpscoutemail.com", "Help Scout mail"),
    ("mandrillapp.com", "Mandrill / Mailchimp Transactional"),
    ("postmarkapp.com", "Postmark mail"),
    ("pepipost.com", "Pepipost mail"),
    ("sparkpostmail", "SparkPost mail"),
    ("brevo", "Brevo / Sendinblue mail"),
    ("freshdesk", "Freshdesk mail"),
]


def _doh_txt(name: str, timeout: int) -> list:
    """Resolve TXT records for `name` via Google DNS-over-HTTPS, Cloudflare fallback."""
    last_error = None
    for endpoint in DOH_ENDPOINTS:
        try:
            headers = {"accept": "application/dns-json"}
            r = requests.get(endpoint, params={"name": name, "type": "TXT"},
                             headers=headers, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            answers = data.get("Answer") or []
            out = []
            for a in answers:
                if a.get("type") != 16:  # TXT = 16
                    continue
                raw = a.get("data", "")
                # DoH returns TXT with literal quotes and occasional split strings.
                cleaned = re.sub(r'"\s*"', "", raw).strip('"').strip()
                if cleaned:
                    out.append(cleaned)
            return out
        except requests.RequestException as e:
            last_error = str(e)
            continue
        except ValueError as e:
            last_error = f"json: {e}"
            continue
    if last_error:
        raise RuntimeError(last_error)
    return []


def fetch(domain: str, raw: bool = False, timeout: int = DEFAULT_TIMEOUT) -> dict:
    domain = domain.strip().lower().lstrip(".")
    if domain.startswith(("http://", "https://")):
        domain = urlparse(domain).netloc

    out = {
        "domain": domain,
        "txt_records": [],
        "services_detected": [],
        "spf_includes": [],
        "dmarc": None,
    }
    try:
        records = _doh_txt(domain, timeout)
    except RuntimeError as e:
        out["error"] = f"dns lookup failed: {e}"
        return out

    out["txt_records"] = records

    # Also fetch DMARC — always lives at _dmarc.<domain>
    try:
        dmarc = _doh_txt(f"_dmarc.{domain}", timeout)
        if dmarc:
            out["dmarc"] = dmarc[0]
    except RuntimeError:  # noqa: silent — DMARC absence is valid signal, not error
        pass

    # Scan every TXT record for SaaS tokens + SPF includes.
    services: list = []
    for rec in records:
        rec_l = rec.lower()
        for sig, label in TOKEN_SIGNATURES:
            if sig.lower() in rec_l and label not in services:
                services.append(label)
        if rec_l.startswith("v=spf1"):
            # Extract include: targets
            for tok in rec_l.split():
                if tok.startswith("include:"):
                    target = tok.split(":", 1)[1]
                    if target not in out["spf_includes"]:
                        out["spf_includes"].append(target)
            for sig, label in SPF_SIGNATURES:
                if sig.lower() in rec_l and label not in services:
                    services.append(label)

    out["services_detected"] = services

    if not raw:
        # Suppress the long TXT blob in default output — it's noisy.
        out.pop("txt_records", None)
    return out


def main(argv: Optional[list] = None) -> int:
    argv = argv if argv is not None else sys.argv
    if len(argv) < 2:
        print("Usage: python -m supersearch.scrapers.dns_txt <domain> [--raw]")
        return 1
    raw = "--raw" in argv
    result = fetch(argv[1], raw=raw)
    print(json.dumps(result, indent=2))
    return 0 if "error" not in result else 2


if __name__ == "__main__":
    sys.exit(main())
