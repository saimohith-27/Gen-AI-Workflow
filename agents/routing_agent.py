def routing_agent(category: str) -> str:
    mapping = {
        # IT-related
        "account_creation": "it",
        "access_request": "it",
        "password_reset": "it",
        "system_issue": "it",
        "software_request": "it",
        "hardware_request": "it",
        "network_issue": "it",

        # HR-related
        "onboarding": "hr",
        "offboarding": "hr",
        "hr_request": "hr",

        # Finance-related
        "payroll": "finance",
        "finance_request": "finance",

        # Legal
        "legal_request": "legal",
        "compliance": "legal",

        # Sales
        "sales_request": "sales",

        # Approval flow
        "approval_request": "manager",

        # General issues / fallback infra
        "issue": "lead",
        "complaint": "lead",

        # Optional infra-type (if used)
        "operations": "pwd"
    }

    return mapping.get(category.lower(), "manager")