"""
Retail AI Assistant – Response Sanitization and Validation
"""
import re
import json

def validate_and_sanitize_response(message: str, reply: str) -> str:
    """Clean up formatting issues in agent output."""
    lines           = reply.split("\n")
    sanitized_lines = []

    for line in lines:
        stripped = line.strip()

        # Remove horizontal rules
        if stripped.startswith("---") or stripped.startswith("==="):
            continue

        # Strip markdown headers
        if stripped.startswith("#"):
            line = re.sub(r"^#+\s*", "", line)

        # Convert markdown bullets to unicode
        if stripped.startswith("* ") or stripped.startswith("- "):
            line = "• " + stripped[2:]
        elif (
            (stripped.startswith("*") or stripped.startswith("-"))
            and not stripped.startswith("**")
            and not stripped.startswith("--")
            and not (stripped.startswith("-") and len(stripped) > 1 and stripped[1].isdigit())
            and not (stripped.startswith("*") and stripped.count("*") > 1)
        ):
            line = "• " + stripped[1:]

        sanitized_lines.append(line)

    sanitized = "\n".join(sanitized_lines)

    # Convert markdown links to plain text
    sanitized = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", sanitized)

    # Mask internal DB IDs unless explicitly requested
    if (
        "id" not in message.lower()
        and "code" not in message.lower()
        and "reference" not in message.lower()
    ):
        sanitized = re.sub(r"\bCUST-\d+\b", "", sanitized)
        sanitized = re.sub(r"\bSTR-\d+\b",  "", sanitized)

    return sanitized.replace("  ", " ").strip()


async def run_validation_layer(query: str, reply: str) -> str:
    """Detect formatting violations and sanitize output."""
    failures = []

    if "#" in reply or "---" in reply or "===" in reply:
        failures.append("markdown headers or horizontal rules")

    if "\n* " in reply or "\n- " in reply or reply.startswith("* ") or reply.startswith("- "):
        failures.append("markdown bullets (use unicode • instead)")

    if (
        re.search(r"\b\d+\s+(?:in stock|available|items|units|qty|quantity)\b", reply.lower())
        or "quantity:" in reply.lower()
    ):
        failures.append("raw stock quantities exposed")

    if (
        (re.search(r"\bCUST-\d+\b", reply) or re.search(r"\bSTR-\d+\b", reply))
        and "id" not in query.lower()
        and "code" not in query.lower()
        and "reference" not in query.lower()
    ):
        failures.append("internal database IDs exposed")

    if failures:
        print(f"[AgentRouter] Validation issues: {failures}. Sanitizing.")

    return validate_and_sanitize_response(query, reply)


def is_raw_routing_json(text: str) -> bool:
    """Detect if a Foundry agent returned its routing plan JSON instead of a real reply."""
    stripped = text.strip()
    # Clean markdown code fences if present
    clean = re.sub(r"^```(?:json)?\n?", "", stripped, flags=re.IGNORECASE)
    clean = re.sub(r"\n?```$", "", clean).strip()
    if not (clean.startswith("[") or clean.startswith("{")):
        return False
    try:
        parsed = json.loads(clean)
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            if "agent" in parsed[0] and "task_query" in parsed[0]:
                return True
    except Exception:
        pass
    return False
