"""
Agent Router – Azure AI Foundry Agents + GPT-4o direct fallback.

Auth strategy (API key only – no az login needed):
  - Agents:    azure-ai-agents  →  AgentsClient(endpoint, AzureKeyCredential)
  - GPT-4o:    openai           →  AzureOpenAI(azure_endpoint, api_key, api_version)

The project endpoint from AI Foundry is used for both:
  AZURE_AI_FOUNDRY_PROJECT_ENDPOINT  →  AgentsClient
  AZURE_OPENAI_ENDPOINT              →  AzureOpenAI (direct chat completions)
"""

import os
from typing import Any

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import MessageTextContent, RunStatus
from azure.core.credentials import AzureKeyCredential
from azure.identity import InteractiveBrowserCredential
from openai import AzureOpenAI

# ─── Intent keywords ──────────────────────────────────────────────────────────

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

AGENT_ENV_MAP = {
    "order":    "AZURE_AGENT_ORDER_ID",
    "refund":   "AZURE_AGENT_REFUND_ID",
    "delivery": "AZURE_AGENT_DELIVERY_ID",
    "store":    "AZURE_AGENT_STORE_ID",
}


def classify_intent(message: str) -> str:
    """Keyword-based intent classifier – returns the best-matching intent."""
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
                f' | Refund: {r["status"]} £{r["amount"]:.2f}'
                f' (ref {r["reference"]}, reason: {r["reason"]})'
            )
        orders_summary.append(
            f'  {o["order_id"]} [{o["status"]}] '
            f'£{o["total"]:.2f} – {item_names}{refund_info}'
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

    return f"""=== RETAIL AI ASSISTANT CONTEXT ===
Customer: {customer['name']} (ID: {customer['id']})
Loyalty: {customer['loyalty_tier']} – {customer['loyalty_points']} Nectar points
Address: {customer['default_address']['line1']}, {customer['default_address']['city']}

ORDERS:
{chr(10).join(orders_summary)}

STORES:
{chr(10).join(stores_summary)}

POLICIES:
- Refund window: {policies['refund_window_days']} days
- Damaged goods: {policies['damaged_goods']}
- Missing items: {policies['missing_items']}
- Substitutions: {policies['substitutions']}

Always be helpful, warm, and solution-oriented. Address the customer as {first_name}.
Never fabricate order details. Only reference the data above.
If asked about something not covered, say you will connect them with a specialist team.
"""


class AgentRouter:
    def __init__(self, customer_data: dict, store_data: dict):
        self.customer_data = customer_data
        self.store_data = store_data
        self.context = build_context_block(customer_data, store_data)
        self._agents_client: AgentsClient | None = None
        self._openai_client: AzureOpenAI | None = None
        self._init_clients()

    def _init_clients(self):
        """
        Initialise both clients.

        AgentsClient  → azure-ai-agents, uses project endpoint + ChainedTokenCredential (Entra ID + Browser)
        AzureOpenAI   → openai package, uses Azure OpenAI endpoint + api_key
        """
        api_key           = os.getenv("AZURE_AI_FOUNDRY_API_KEY", "").strip()
        project_endpoint  = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
        openai_endpoint   = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()

        # ── AgentsClient (for pre-created agent threads) ──────────────────────
        if project_endpoint:
            try:
                tenant_id = os.getenv("AZURE_TENANT_ID", "").strip() or None
                self._agents_client = AgentsClient(
                    endpoint=project_endpoint,
                    credential=InteractiveBrowserCredential(
                        connection_verify=False,
                        tenant_id=tenant_id,
                    ),
                )
                print("[AgentRouter] AgentsClient initialised [OK]")
            except Exception as exc:
                print(f"[AgentRouter] AgentsClient init failed: {exc}")
                self._agents_client = None

        # ── AzureOpenAI (direct GPT-4o fallback) ─────────────────────────────
        if api_key and openai_endpoint:
            try:
                # Strip trailing /v1 if present – the SDK appends its own path
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
            print(
                "[AgentRouter] WARNING: No Azure clients initialised. "
                "Check AZURE_AI_FOUNDRY_API_KEY, AZURE_AI_FOUNDRY_PROJECT_ENDPOINT, "
                "and AZURE_OPENAI_ENDPOINT in your .env file."
            )

    def _get_agent_id(self, intent: str) -> str | None:
        env_key = AGENT_ENV_MAP.get(intent)
        if not env_key:
            return None
        val = os.getenv(env_key, "").strip()
        return val if val else None

    async def _call_agent(
        self, agent_id: str, message: str, history: list[dict]
    ) -> str:
        """
        Open an agent thread, replay history, post the new message, poll the run.
        Uses azure-ai-agents AgentsClient (supports AzureKeyCredential).
        """
        client = self._agents_client

        thread = client.threads.create()

        # First message: inject full data context
        client.messages.create(
            thread_id=thread.id,
            role="user",
            content=(
                "[SYSTEM CONTEXT – internal only, do not repeat to user]\n"
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

        # Post the new user message
        client.messages.create(
            thread_id=thread.id,
            role="user",
            content=message,
        )

        # Run and poll until completion
        run = client.runs.create_and_process(
            thread_id=thread.id,
            agent_id=agent_id,
        )

        if run.status == RunStatus.FAILED:
            raise RuntimeError(f"Agent run failed: {run.last_error}")

        # Extract latest assistant reply
        messages = client.messages.list(thread_id=thread.id)
        for msg in messages.data:
            if msg.role == "assistant":
                for block in msg.content:
                    if isinstance(block, MessageTextContent):
                        return block.text.value

        return "I'm sorry, I couldn't generate a response. Please try again."

    async def _call_gpt4o_direct(
        self, intent: str, message: str, history: list[dict]
    ) -> str:
        """
        Direct GPT-4o chat completion via the Azure OpenAI endpoint.
        Used when no agent IDs are configured, or as fallback on agent failure.
        """
        if not self._openai_client:
            raise RuntimeError(
                "AzureOpenAI client not initialised. "
                "Set AZURE_AI_FOUNDRY_API_KEY and AZURE_OPENAI_ENDPOINT in .env"
            )

        deployment = os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-4o")

        system_prompt = (
            f"You are a friendly, knowledgeable Sainsbury's retail assistant. "
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

    async def handle(self, message: str, history: list[dict]) -> dict[str, Any]:
        intent   = classify_intent(message)
        agent_id = self._get_agent_id(intent)

        # Use agent if available, else fall back to direct GPT-4o
        if self._agents_client and agent_id:
            try:
                reply    = await self._call_agent(agent_id, message, history)
                strategy = "foundry_agent"
            except Exception as exc:
                print(f"[AgentRouter] Agent call failed ({exc}), falling back to GPT-4o")
                reply    = await self._call_gpt4o_direct(intent, message, history)
                strategy = "gpt4o_direct_fallback"
        else:
            reply    = await self._call_gpt4o_direct(intent, message, history)
            strategy = "gpt4o_direct"

        return {
            "reply":   reply,
            "intent":  intent,
            "sources": [strategy],
        }
