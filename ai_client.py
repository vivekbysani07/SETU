"""
AI classification and policy-brief generation.

Real mode: if GEMINI_API_KEY is set, every call goes to Gemini (Google AI
Studio / Vertex AI credentials both work with the same key via
google-generativeai). Model name is configurable via GEMINI_MODEL; the
default is the "latest flash" alias so this doesn't silently break as
Google retires specific model versions.

Offline mock mode: if no key is configured, classify_request() and
generate_brief() fall back to a small deterministic heuristic so the
backend, database, and API are fully testable and demoable without any
external network call or API key. This fallback is NOT the real system —
it exists purely so reviewers can run `uvicorn main:app` immediately.
"""
import os
import json
import re

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

SECTORS = [
    "Water & sanitation", "Roads & transport", "Healthcare",
    "Electricity", "Education", "Public safety", "Other",
]

SEVERITY_RUBRIC = """Score severity strictly against this rubric — pick the single best-fitting level, do not average:
1 = Minor inconvenience or cosmetic issue; no real effect on daily life or safety.
2 = Ongoing but manageable nuisance; noticeable disruption to comfort or convenience.
3 = Significant disruption to daily activity, livelihood, or access to a basic service, but no immediate danger.
4 = Serious impact on health, safety, or livelihood, affecting many people or repeated over time; needs attention within weeks.
5 = Critical or emergency: immediate risk to life, health, or safety, or complete loss of an essential service (water, power, medical access) for an extended period.
Base the score only on what the message actually describes (severity of impact, duration, number of people affected) — not on tone, punctuation, or how dramatically it is phrased."""

_client = None
if GEMINI_API_KEY:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    _client = genai.GenerativeModel(GEMINI_MODEL)


def _extract_json(text):
    cleaned = re.sub(r"```json|```", "", text).strip()
    return json.loads(cleaned)


_JSON_CONFIG = {"response_mime_type": "application/json"}


def classify_request(text: str) -> dict:
    """Returns: detected_language, translated_english, sector, severity, severity_reason, summary"""
    if _client:
        prompt = (
            "You are a multilingual civic-request classifier for a citizen feedback platform used by a "
            "national government. The citizen may write in one language, or mix languages in the same "
            "message (code-switching) — detect this yourself, do not assume.\n\n"
            f"{SEVERITY_RUBRIC}\n\n"
            "Return ONLY valid JSON (no markdown fences, no preamble) with exactly these keys:\n"
            '{"detected_language": string, "translated_english": string, '
            f'"sector": one of {json.dumps(SECTORS)}, '
            '"severity": integer 1-5 per the rubric above, '
            '"severity_reason": one short phrase citing which rubric level applied and why, '
            '"summary": a short one-sentence English summary}\n\n'
            f"Message: {text}"
        )
        try:
            response = _client.generate_content(prompt, generation_config=_JSON_CONFIG)
            parsed = _extract_json(response.text)
            parsed["severity"] = max(1, min(5, int(parsed.get("severity", 3))))
            if parsed.get("sector") not in SECTORS:
                parsed["sector"] = "Other"
            return parsed
        except Exception:
            # A transient Gemini error (rate limit, safety block, malformed
            # output) should never take the whole request down — fall back
            # to the offline heuristic for just this one submission instead.
            result = _mock_classify(text)
            result["severity_reason"] = "Live classification failed for this message; used the offline fallback."
            return result

    return _mock_classify(text)


def generate_brief(region, sector, count, avg_severity, poverty, infra, investment, samples) -> dict:
    """Returns: project_title, brief"""
    if _client:
        prompt = (
            "You are drafting a short policy brief for a national policymaker reviewing citizen-driven "
            "infrastructure priorities. Return ONLY valid JSON (no markdown fences): "
            '{"project_title": short actionable project name under 8 words, '
            '"brief": 3-4 plain sentences explaining why this deserves priority, referencing the data given}\n\n'
            f"Region: {region}\nSector: {sector}\nRequests received: {count}\n"
            f"Average urgency: {avg_severity:.1f}/5\nRegional poverty index: {poverty}\n"
            f"Infrastructure adequacy score: {infra} (lower = bigger gap)\n"
            f"Existing public investment level: {investment} (lower = underinvested)\n"
            f"Sample citizen concerns:\n" + "\n".join(f"- {s}" for s in samples)
        )
        try:
            response = _client.generate_content(prompt, generation_config=_JSON_CONFIG)
            return _extract_json(response.text)
        except Exception:
            return _mock_brief(region, sector, count, avg_severity, poverty, infra, investment)

    return _mock_brief(region, sector, count, avg_severity, poverty, infra, investment)


# ---------------------------------------------------------------------------
# Offline mock fallback — deterministic, no network, no API key required.
# Exists only so the service is runnable/demoable out of the box.
# ---------------------------------------------------------------------------

_SECTOR_KEYWORDS = {
    "Water & sanitation": ["water", "pani", "sewage", "drain", "toilet", "agua", "vода", "水"],
    "Roads & transport": ["road", "pothole", "street", "bus", "traffic", "rua", "дорог", "路"],
    "Healthcare": ["doctor", "hospital", "clinic", "health", "medicine", "sick", "médic", "医"],
    "Electricity": ["power", "electricity", "outage", "light", "grid", "luz", "элект", "电"],
    "Education": ["school", "teacher", "student", "escola", "школ", "学校"],
    "Public safety": ["crime", "unsafe", "danger", "police", "accident", "segur", "безопас"],
}
_URGENT_WORDS = ["emergency", "dying", "critical", "no water", "no power", "weeks", "months",
                 "children", "sick", "accident", "daily", "urgent"]


def _mock_classify(text: str) -> dict:
    lower = text.lower()
    sector = "Other"
    for s, keywords in _SECTOR_KEYWORDS.items():
        if any(k in lower for k in keywords):
            sector = s
            break
    hits = sum(1 for w in _URGENT_WORDS if w in lower)
    severity = min(5, max(2, 2 + hits))
    return {
        "detected_language": "Unknown (offline mock mode)",
        "translated_english": text,
        "sector": sector,
        "severity": severity,
        "severity_reason": f"Mock heuristic: {hits} urgency keyword(s) matched — set GEMINI_API_KEY for real scoring.",
        "summary": text[:140] + ("..." if len(text) > 140 else ""),
    }


def _mock_brief(region, sector, count, avg_severity, poverty, infra, investment) -> dict:
    return {
        "project_title": f"Priority review: {sector} in {region}",
        "brief": (
            f"[Offline mock brief — set GEMINI_API_KEY for real generation] "
            f"{count} citizen request(s) from {region} flagged {sector.lower()} issues at an average "
            f"urgency of {avg_severity:.1f}/5. Combined with a poverty index of {poverty} and an "
            f"infrastructure adequacy score of {infra} (lower means a bigger existing gap), and current "
            f"public investment level of {investment}, this cluster warrants policymaker attention."
        ),
    }
