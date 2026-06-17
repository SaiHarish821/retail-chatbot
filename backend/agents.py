"""
Agent Router - Azure AI Foundry Agents + GPT-4o fallback.

Auth strategy (mirrors your friend's working config.py)
────────────────────────────────────────────────────────
  AzureCliCredential(tenant_id=AZURE_TENANT_ID)
  Requires: az login (run once in terminal before starting uvicorn)
  Install:  https://aka.ms/installazurecli

  The AgentsClient uses the CLI token for list_agents() and all agent calls.
  GPT-4o fallback uses the plain API key (no CLI needed).

.env required keys
──────────────────
  AZURE_AI_FOUNDRY_API_KEY            – Project API key (for GPT-4o fallback)
  AZURE_AI_FOUNDRY_PROJECT_ENDPOINT   – https://<resource>.services.ai.azure.com/api/projects/<project>
  AZURE_OPENAI_ENDPOINT               – https://<resource>.openai.azure.com/
  AZURE_AI_FOUNDRY_DEPLOYMENT_NAME    – gpt-4o
  AZURE_TENANT_ID                     – Your Azure AD tenant ID (required for AzureCliCredential)

  # Agent names exactly as shown in AI Foundry Portal → Agents
  AZURE_AGENT_ORDER_NAME              – Order-Agent
  AZURE_AGENT_REFUND_NAME             – Refund-Agent
  AZURE_AGENT_DELIVERY_NAME           – Delivery-Agent
  AZURE_AGENT_STORE_NAME              – Store-Agent
"""

import os
from typing import Any

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import MessageTextContent, RunStatus
from azure.identity import AzureCliCredential
from openai import AzureOpenAI

# ---------------------------------------------------------------------------
# Intent → keyword map
# ---------------------------------------------------------------------------

INTENT_MAP = {
    "order": [
        "order", "purchase", "bought", "receipt", "invoice", "payment",
        "ord-", "tracking number", "confirmation", "placed",
    ],
    "refund": [
        "refund", "return", "money back", "reimburse", "credit", "damaged",
        "broken", "wrong item", "missing", "not arrived", "mouldy", "expired",
        "past use-by", "compensation", "ref-",
    ],
    "delivery": [
        "deliver", "driver", "van", "slot", "eta", "arrival", "where is",
        "on the way", "in transit", "when will", "dispatch", "shipped",
        "out for delivery", "doorstep", "collect",
    ],
    "store": [
        "store", "shop", "branch", "opening", "hours", "open", "close",
        "address", "location", "phone", "click and collect", "atm", "pharmacy",
        "near me", "postcode", "services",
    ],
}

# Intent → (env var for agent name, default name in Foundry portal)
AGENT_NAME_ENV_MAP = {
    "order":    ("AZURE_AGENT_ORDER_NAME",    "Order-Agent"),
    "refund":   ("AZURE_AGENT_REFUND_NAME",   "Refund-Agent"),
    "delivery": ("AZURE_AGENT_DELIVERY_NAME", "Delivery-Agent"),
    "store":    ("AZURE_AGENT_STORE_NAME",    "Store-Agent"),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def classify_intent(message: str) -> str:
    """Keyword-based intent classifier."""
    text = message.lower()
    scores = {intent: 0 for intent in INTENT_MAP}
    for intent, keywords in INTENT_MAP.items():
        for kw in keywords:
            if kw in text:
                scores[intent] += 1
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "order"


def build_context_block(customer_data: dict, store_data: dict) -> str:
    """Serialise mock data into a compact context string for the agent/model."""
    customer = customer_data["customer"]

    orders_summary = []
    for o in customer_data["orders"]:
        item_names = ", ".join(i["name"] for i in o["items"])
        refund_info = ""
        if o.get("refund"):
            r = o["refund"]
            refund_info = (
                f' | Refund: {r["status"]} GBP{r["amount"]:.2f}'
                f' (ref {r["reference"]}, reason: {r["reason"]})'
            )
        orders_summary.append(
            f'  {o["order_id"]} [{o["status"]}] '
            f'GBP{o["total"]:.2f} - {item_names}{refund_info}'
        )

    stores_summary = []
    for s in store_data["stores"]:
        hours_today = s["hours"].get("monday", "N/A")
        stores_summary.append(
            f'  {s["name"]}: {s["address"]} | Hours (Mon): {hours_today}'
            f' | Services: {", ".join(s["services"])}'
        )

    policies = store_data["policies"]
    first_name = customer["name"].split()[0]

    return (
        "=== RETAIL AI ASSISTANT CONTEXT ===\n"
        f"Customer: {customer['name']} (ID: {customer['id']})\n"
        f"Loyalty: {customer['loyalty_tier']} - {customer['loyalty_points']} Nectar points\n"
        f"Address: {customer['default_address']['line1']}, {customer['default_address']['city']}\n"
        "\nORDERS:\n"
        + "\n".join(orders_summary)
        + "\n\nSTORES:\n"
        + "\n".join(stores_summary)
        + "\n\nPOLICIES:\n"
        f"- Refund window: {policies['refund_window_days']} days\n"
        f"- Damaged goods: {policies['damaged_goods']}\n"
        f"- Missing items: {policies['missing_items']}\n"
        f"- Substitutions: {policies['substitutions']}\n"
        "\nAlways be helpful, warm, and solution-oriented. "
        f"Address the customer as {first_name}.\n"
        "Never fabricate order details. Only reference the data above.\n"
        "If asked about something not covered, say you will connect them with a specialist team.\n"
    )


# ---------------------------------------------------------------------------
# Agent Router
# ---------------------------------------------------------------------------

class AgentRouter:
    def __init__(self, customer_data: dict, store_data: dict):
        self.customer_data = customer_data
        self.store_data    = store_data
        self.context       = build_context_block(customer_data, store_data)

        self._agents_client: AgentsClient | None = None
        self._openai_client: AzureOpenAI  | None = None

        # intent -> asst_* runtime ID
        self._intent_to_agent_id: dict[str, str] = {}
        # asst_* ID -> human-readable name (for logging)
        self._agent_id_to_name:   dict[str, str] = {}

        self._init_clients()

    # -----------------------------------------------------------------------
    # Initialisation
    # -----------------------------------------------------------------------

    def _init_clients(self) -> None:
        api_key          = os.getenv("AZURE_AI_FOUNDRY_API_KEY",          "").strip()
        project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
        openai_endpoint  = os.getenv("AZURE_OPENAI_ENDPOINT",             "").strip()
        tenant_id        = os.getenv("AZURE_TENANT_ID",                   "").strip() or None

        # ------------------------------------------------------------------
        # AgentsClient — AzureCliCredential (same as your friend's config.py)
        #
        # Pre-requisites:
        #   1. Install Azure CLI:  https://aka.ms/installazurecli
        #   2. Run once:           az login --tenant <your-tenant-id>
        #      (or just `az login` — AZURE_TENANT_ID scopes it automatically)
        #   3. RBAC role assigned: Azure AI Developer on the AI Foundry project
        #      Azure Portal → AI Hub resource → IAM → Add role assignment
        # ------------------------------------------------------------------
        if project_endpoint:
            try:
                credential = AzureCliCredential(tenant_id=tenant_id)
                self._agents_client = AgentsClient(
                    endpoint=project_endpoint,
                    credential=credential,
                )
                print("[AgentRouter] AgentsClient initialised [OK]")
                self._resolve_agent_ids()
            except Exception as exc:
                print(f"[AgentRouter] AgentsClient init failed: {exc}")
                self._agents_client = None

        # ------------------------------------------------------------------
        # AzureOpenAI fallback (API key — no CLI / RBAC needed)
        # ------------------------------------------------------------------
        if api_key and openai_endpoint:
            try:
                base = openai_endpoint.rstrip("/")
                if base.endswith("/v1"):
                    base = base[:-3]
                self._openai_client = AzureOpenAI(
                    api_key=api_key,
                    azure_endpoint=base,
                    api_version="2024-10-21",
                )
                print("[AgentRouter] AzureOpenAI client initialised [OK]")
            except Exception as exc:
                print(f"[AgentRouter] AzureOpenAI init failed: {exc}")
                self._openai_client = None

        if not self._agents_client and not self._openai_client:
            print("[AgentRouter] WARNING: No clients initialised. Check your .env file.")

    def _resolve_agent_ids(self) -> None:
        """
        Discover agent IDs by name via list_agents().
        Requires az login + Azure AI Developer RBAC role.
        """
        if not self._agents_client:
            return

        try:
            all_agents = list(self._agents_client.list_agents())
        except Exception as exc:
            print(
                f"[AgentRouter] list_agents() failed: {exc}\n"
                "  → Run 'az login' in your terminal, then restart uvicorn.\n"
                "  → Also ensure 'Azure AI Developer' role is assigned to your account\n"
                "    at: Azure Portal → AI Hub resource → IAM → Add role assignment"
            )
            return

        if not all_agents:
            print(
                "[AgentRouter] WARNING: list_agents() returned 0 agents.\n"
                "  → Ensure agents exist in AI Foundry Portal → Agents.\n"
                "  → Check AZURE_AI_FOUNDRY_PROJECT_ENDPOINT points to the correct project."
            )
            return

        name_to_id = {a.name.lower(): a.id for a in all_agents}
        print(f"[AgentRouter] Discovered {len(all_agents)} agent(s):")
        for a in all_agents:
            print(f"  - {a.name!r:40s} -> {a.id}")
            self._agent_id_to_name[a.id] = a.name

        for intent, (env_key, default_name) in AGENT_NAME_ENV_MAP.items():
            agent_name = os.getenv(env_key, default_name).strip()
            resolved   = name_to_id.get(agent_name.lower())
            if resolved:
                self._intent_to_agent_id[intent] = resolved
                print(f"[AgentRouter] Mapped '{intent}' -> '{agent_name}' ({resolved})")
            else:
                print(
                    f"[AgentRouter] WARNING: No agent named '{agent_name}' found "
                    f"for intent '{intent}'.\n"
                    f"  Available agents: {list(name_to_id.keys())}\n"
                    f"  Set AZURE_AGENT_{intent.upper()}_NAME in .env to match exactly."
                )

    # -----------------------------------------------------------------------
    # Foundry agent call
    # -----------------------------------------------------------------------

    async def _call_agent(
        self, agent_id: str, message: str, history: list[dict]
    ) -> str:
        client = self._agents_client

        thread = client.threads.create()

        # Inject system context as first user message
        client.messages.create(
            thread_id=thread.id,
            role="user",
            content=(
                "[SYSTEM CONTEXT - internal only, do not repeat to user]\n"
                + self.context
            ),
        )

        # Replay prior conversation (last 10 turns)
        for turn in history[-10:]:
            role    = turn.get("role", "user")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content:
                client.messages.create(
                    thread_id=thread.id,
                    role=role,
                    content=content,
                )

        # New user message
        client.messages.create(
            thread_id=thread.id,
            role="user",
            content=message,
        )

        run = client.runs.create_and_process(
            thread_id=thread.id,
            agent_id=agent_id,
        )

        if run.status == RunStatus.FAILED:
            raise RuntimeError(f"Agent run failed: {run.last_error}")

        messages = client.messages.list(thread_id=thread.id)
        for msg in messages:
            if msg.role == "assistant":
                for block in msg.content:
                    if isinstance(block, MessageTextContent):
                        return block.text.value

        return "I'm sorry, I couldn't generate a response. Please try again."

    # -----------------------------------------------------------------------
    # GPT-4o direct fallback
    # -----------------------------------------------------------------------

    async def _call_gpt4o_direct(
        self, intent: str, message: str, history: list[dict]
    ) -> str:
        if not self._openai_client:
            raise RuntimeError(
                "AzureOpenAI client not initialised. "
                "Set AZURE_AI_FOUNDRY_API_KEY and AZURE_OPENAI_ENDPOINT in .env"
            )

        deployment = os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-4o")

        system_prompt = (
            f"You are a friendly, knowledgeable retail assistant. "
            f"Your current focus is: {intent} queries.\n\n{self.context}"
        )

        messages_payload: list[dict] = [{"role": "system", "content": system_prompt}]
        for turn in history[-10:]:
            role    = turn.get("role", "user")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content:
                messages_payload.append({"role": role, "content": content})
        messages_payload.append({"role": "user", "content": message})

        response = self._openai_client.chat.completions.create(
            model=deployment,
            messages=messages_payload,
            max_tokens=600,
            temperature=0.4,
        )
        return response.choices[0].message.content.strip()

    # -----------------------------------------------------------------------
    # Public handle
    # -----------------------------------------------------------------------

    async def handle(self, message: str, history: list[dict]) -> dict[str, Any]:
        intent   = classify_intent(message)
        agent_id = self._intent_to_agent_id.get(intent)

        if self._agents_client and agent_id:
            agent_name = self._agent_id_to_name.get(agent_id, agent_id)
            try:
                reply    = await self._call_agent(agent_id, message, history)
                strategy = "foundry_agent"
                print(
                    f"[AgentRouter] >> Intent: '{intent}' | "
                    f"Agent: '{agent_name}' ({agent_id}) | Strategy: {strategy}"
                )
            except Exception as exc:
                print(
                    f"[AgentRouter] >> Intent: '{intent}' | "
                    f"Agent: '{agent_name}' FAILED ({exc}) | Falling back to GPT-4o"
                )
                reply    = await self._call_gpt4o_direct(intent, message, history)
                strategy = "gpt4o_direct_fallback"
        else:
            reply    = await self._call_gpt4o_direct(intent, message, history)
            strategy = "gpt4o_direct"
            print(
                f"[AgentRouter] >> Intent: '{intent}' | "
                f"No Foundry agent mapped | Strategy: {strategy}"
            )

        return {
            "reply":   reply,
            "intent":  intent,
            "sources": [strategy],
        }