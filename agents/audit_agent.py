from typing import List


def audit_agent(logs: List[str], message: str) -> List[str]:
    logs.append(message)
    return logs
