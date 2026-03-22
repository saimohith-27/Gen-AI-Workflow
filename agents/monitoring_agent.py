def monitoring_agent(status: str, priority: str) -> str:
    if priority == "high" and status == "Pending":
        return "Escalated"
    return status
