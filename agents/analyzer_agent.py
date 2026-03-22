import json
import os

import google.genai as genai


VALID_ROUTING = {"hr", "manager", "lead", "sales", "legal", "pwd", "finance", "it"}


def _deterministic_routing_fallback(prompt: str) -> str:
    text = (prompt or "").lower()

    it_keywords = [
        "bug",
        "application",
        "app",
        "software",
        "system",
        "access",
        "password",
        "network",
        "server",
        "crash",
        "error",
        "login",
    ]
    finance_keywords = ["invoice", "payment", "reimbursement", "budget", "finance", "payroll"]
    hr_keywords = [
        "onboarding",
        "offboarding",
        "employee",
        "hiring",
        "leave",
        "hr",
        "salary",
        "hike",
        "increment",
        "compensation",
        "promotion",
    ]
    legal_keywords = ["contract", "legal", "compliance", "nda", "policy"]
    sales_keywords = ["client", "deal", "sales", "lead"]
    pwd_keywords = ["road", "electricity", "water", "building", "facility", "infrastructure"]

    if any(keyword in text for keyword in it_keywords):
        return "it"
    if any(keyword in text for keyword in finance_keywords):
        return "finance"
    if any(keyword in text for keyword in hr_keywords):
        return "hr"
    if any(keyword in text for keyword in legal_keywords):
        return "legal"
    if any(keyword in text for keyword in sales_keywords):
        return "sales"
    if any(keyword in text for keyword in pwd_keywords):
        return "pwd"
    return "manager"


def analyzer_agent(prompt: str) -> dict:
    gemini_api_key = os.getenv("GEMINI_API_KEY")

    if not gemini_api_key:
        return {
            "summary": "Mock analysis",
            "category": "General",
            "priority": "normal",
            "routing": "Public Works",
            "tags": ["demo"],
            "action": "Enable API key",
        }

    structured_prompt = f"""
You are an AI system for analyzing internal workflow requests.

Return ONLY valid JSON:
{{
  "summary": "...",
  "category": "...",
  "priority": "low / normal / high",
  "routing": "hr / manager / lead / sales / legal / pwd / finance / it",
  "tags": ["..."],
  "action": "..."
}}

Rules:
- category must describe the type of request clearly
- routing must be automatically decided based on category and request content
- do NOT use fixed mapping — infer the correct department

Routing Guidelines:
- account_creation, access_request, password_reset, bug_fix, system_issue → it
- system_issue, software_request, hardware_request → it
- payroll, finance_request → finance
- hr_request, onboarding, offboarding → hr
- legal_request, compliance → legal
- sales_request → sales
- approval_request → manager or lead (based on context)
- complaints/issues related to infrastructure → pwd
- if unclear → manager

- summary should be one short sentence
- tags should be 2–5 relevant keywords
- action should describe the next step clearly

Complaint:
{prompt}
"""

    try:
        client = genai.Client(api_key=gemini_api_key)
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=structured_prompt,
        )
        text = response.text.strip().replace("```json", "").replace("```", "")
        parsed = json.loads(text)

        fallback_routing = _deterministic_routing_fallback(prompt)
        ai_routing = str(parsed.get("routing", "")).strip().lower()
        parsed["routing"] = ai_routing if ai_routing in VALID_ROUTING else fallback_routing

        return parsed
    except Exception as e:
        return {
            "summary": f"(AI error) {e}",
            "category": "Unknown",
            "priority": "low",
            "routing": _deterministic_routing_fallback(prompt),
            "tags": [],
            "action": "Manual review needed",
        }
