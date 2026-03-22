import re


def _extract_quantity(text: str) -> int:
    qty_match = re.search(r"\b(\d{1,3})\b", text)
    if qty_match:
        return max(1, int(qty_match.group(1)))
    return 1


def _first_match(text: str, rules: list[tuple[str, str]], default_value: str) -> str:
    for keyword, value in rules:
        if keyword in text:
            return value
    return default_value


def indent_analyzer_agent(indent_text: str) -> dict:
    """Deterministic analyzer for indent requests with budget estimation and routing."""
    normalized = " ".join((indent_text or "").strip().lower().split())
    if not normalized:
        normalized = "general office requirement"

    category_rules = [
        ("hdmi", "it_asset"),
        ("laptop", "it_asset"),
        ("mouse", "it_asset"),
        ("keyboard", "it_asset"),
        ("desk", "workspace"),
        ("chair", "workspace"),
        ("cleaner", "cleaning"),
        ("cleaning", "cleaning"),
        ("repair", "facility"),
        ("electrical", "facility"),
        ("plumbing", "facility"),
    ]

    routing_by_category = {
        "it_asset": "it",
        "workspace": "finance",
        "cleaning": "pwd",
        "facility": "pwd",
        "other": "manager",
    }

    unit_cost_rules = [
        ("laptop", 85000.0),
        ("desk", 15000.0),
        ("chair", 7000.0),
        ("hdmi", 1200.0),
        ("mouse", 700.0),
        ("keyboard", 1100.0),
        ("cleaner", 12000.0),
        ("cleaning", 10000.0),
        ("repair", 25000.0),
        ("electrical", 22000.0),
        ("plumbing", 18000.0),
    ]

    category = _first_match(normalized, category_rules, "other")
    route_to = routing_by_category.get(category, "manager")

    quantity = _extract_quantity(normalized)
    unit_cost = 8000.0
    for keyword, cost in unit_cost_rules:
        if keyword in normalized:
            unit_cost = cost
            break

    estimated_cost = round(quantity * unit_cost, 2)
    if estimated_cost > 150000:
        budget_band = "high"
    elif estimated_cost > 40000:
        budget_band = "medium"
    else:
        budget_band = "low"

    summary = f"Indent for {category.replace('_', ' ')} routed to {route_to}."

    return {
        "summary": summary,
        "category": category,
        "estimated_cost": estimated_cost,
        "budget_band": budget_band,
        "route_to_designation": route_to,
        "reasoning": (
            f"Detected category {category} from request text and estimated quantity {quantity}. "
            f"Applied unit cost {unit_cost:.2f} for budget estimation."
        ),
        "quantity": quantity,
        "unit_cost": unit_cost,
    }
