def priority_agent(analysis: dict, complaint: str):
    complaint_lower = complaint.lower()

    if "no electricity" in complaint_lower or "3 days" in complaint_lower:
        return "high", "24 hours"

    return analysis.get("priority", "normal"), "48 hours"
