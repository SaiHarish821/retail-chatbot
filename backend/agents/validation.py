"""
Retail AI Assistant – Response Sanitization and Validation
"""
import re
import json
import logging

logger = logging.getLogger(__name__)

# Sensitive substrings/regexes that must never be leaked
SENSITIVE_PATTERNS = [
    r"sk-[a-zA-Z0-9]{20,}",       # OpenAI API Keys
    r"endpoint=",                 # Connection string endpoint
    r"accesskey=",                # Connection string accesskey
    r"pwd=",                      # Passwords
    r"password=",                 # Passwords
    r"database\.azure\.com",      # DB Host
    r"sslmode",                   # DB SSL mode
    r"cors_origin",               # CORS config
    r"system prompt",             # Prompts
    r"agent instructions",        # Instructions
    r"specialist_agent_node",     # Code internals
    r"compiled_graph",            # Code internals
    r"langgraph",                 # Library internals
    r"langchain",                 # Library internals
    r"api_key",                   # Keys
    r"connection_string",         # Connection strings
    r"database schema",           # Database schemas
]

# Environment variables that should remain secure
ENV_VARS = [
    "AZURE_TENANT_ID", "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "AZURE_AI_FOUNDRY_DEPLOYMENT_NAME",
    "AZURE_OPENAI_VOICE_DEPLOYMENT_NAME", "AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION",
    "ACS_CONNECTION_STRING", "PUBLIC_CALLBACK_URL", "COGNITIVE_SERVICES_ENDPOINT",
    "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_SSLMODE",
    "AZURE_AI_SEARCH_ENDPOINT", "AZURE_AI_SEARCH_KEY", "AZURE_AI_SEARCH_PRODUCT_INDEX"
]

def check_security_guardrails(message: str, reply: str) -> str:
    """Scan response to block disclosure of credentials, prompts, system variables, or unauthorized customer details."""
    reply_lower = reply.lower()
    
    # 1. API Keys, Connection Strings, Credentials, Hosts
    for pattern in SENSITIVE_PATTERNS:
        if re.search(pattern, reply_lower) or pattern in reply_lower:
            logger.warning(f"[Guardrail] Blocked response containing sensitive pattern: {pattern}")
            return "I am sorry, but I cannot disclose system details. Is there anything else I can help you with regarding Sainsbury's orders, stock, or refunds?"
            
    # 2. Database credentials or system environment variables
    for env in ENV_VARS:
        if env.lower() in reply_lower:
            logger.warning(f"[Guardrail] Blocked response containing system environment variable: {env}")
            return "I am sorry, but I cannot disclose system details. Is there anything else I can help you with regarding Sainsbury's orders, stock, or refunds?"
            
    # 3. Protect other customer's details (e.g. emails not belonging to current customer)
    emails = re.findall(r'[\w\.-]+@[\w\.-]+', reply_lower)
    for email in emails:
        if email not in ["jamie.thornton@example.com", "jamie.thornton@example.co.uk", "saiharish8201@gmail.com"]:
            logger.warning(f"[Guardrail] Blocked response containing third-party email: {email}")
            return "I'm sorry, I am unable to disclose information for other customer accounts. Let's stick to your account details."
            
    return reply

def validate_and_sanitize_response(message: str, reply: str) -> str:
    """Clean up formatting issues in agent output and enforce security guardrails."""
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

    sanitized_result = sanitized.replace("  ", " ").strip()
    
    # Enforce security guardrails
    return check_security_guardrails(message, sanitized_result)


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
