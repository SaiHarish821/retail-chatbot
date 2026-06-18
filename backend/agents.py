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

  # Agent names exactly as shown in AI Foundry Portal -> Agents
  AZURE_AGENT_ORDER_NAME              – Order-Agent
  AZURE_AGENT_REFUND_NAME             – Refund-Agent
  AZURE_AGENT_DELIVERY_NAME           – Delivery-Agent
  AZURE_AGENT_STORE_NAME              – Store-Agent
  AZURE_AGENT_SUPERVISOR_NAME         – Supervisor-Agent
"""

import os
import json
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential
from openai import AzureOpenAI

# ---------------------------------------------------------------------------
# Intent -> keyword map
# ---------------------------------------------------------------------------

INTENT_MAP = {
    "refund": [
        "refund", "return", "money back", "reimburse", "credit", "damaged",
        "broken", "wrong item", "missing", "not arrived", "mouldy", "expired",
        "past use-by", "compensation", "ref-",
    ],
    "delivery": [
        "deliver", "driver", "van", "slot", "eta", "arrival",
        "where is my order", "where is my delivery", "where is the driver", "where is the van", "where is my package", "where is the delivery",
        "on the way", "in transit", "when will", "dispatch", "shipped",
        "out for delivery", "doorstep", "collect",
    ],
    "store": [
        "store", "shop", "branch", "opening", "hours", "open", "close",
        "address", "location", "phone", "click and collect", "atm", "pharmacy",
        "near me", "postcode", "services", "stock", "in stock", "available", "availability",
        "sainsbury", "sainsbury's",
    ],
    "order": [
        "order", "purchase", "bought", "receipt", "invoice", "payment",
        "ord-", "tracking number", "confirmation", "placed",
    ],
}

# Intent -> (env var for agent name, default name in Foundry portal)
AGENT_NAME_ENV_MAP = {
    "supervisor": ("AZURE_AGENT_SUPERVISOR_NAME", "Supervisor-Agent"),
    "order":    ("AZURE_AGENT_ORDER_NAME",    "Order-Agent"),
    "refund":   ("AZURE_AGENT_REFUND_NAME",   "Refund-Agent"),
    "delivery": ("AZURE_AGENT_DELIVERY_NAME", "Delivery-Agent"),
    "store":    ("AZURE_AGENT_STORE_NAME",    "Store-Agent"),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import re

def classify_intent(message: str) -> str:
    """Keyword-based intent classifier using word boundaries to prevent false positives."""
    text = message.lower()
    scores = {intent: 0 for intent in INTENT_MAP}
    for intent, keywords in INTENT_MAP.items():
        for kw in keywords:
            # For short keywords or common prefixes, check word boundary
            if len(kw) <= 3 or kw in ["deliver", "open", "close", "store", "shop"]:
                pattern = r'\b' + re.escape(kw)
                if re.search(pattern, text):
                    scores[intent] += 1
            else:
                if kw in text:
                    scores[intent] += 1
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "order"


def build_context_block(customer_data: dict) -> str:
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

    first_name = customer["name"].split()[0]

    store_context = (
        "\n\n=== STORE LOCATIONS & DETAILS ===\n"
        "1. Sainsbury's Holborn (ID: STR-001)\n"
        "   Address: 1 Kingsway, London, WC2B 6XF\n"
        "   Phone: 020 7831 1000\n"
        "   Hours:\n"
        "     Monday - Friday: 07:00 - 23:00\n"
        "     Saturday: 08:00 - 22:00\n"
        "     Sunday: 11:00 - 17:00\n"
        "   Services: Click & Collect, Pharmacy, ATM, Café, Photo Booth\n"
        "   Click & Collect Cutoff: 23:00 previous day\n"
        "   Nearest Tube: Holborn (Central/Piccadilly)\n"
        "\n"
        "2. Sainsbury's Islington (ID: STR-002)\n"
        "   Address: 2 Tolpuddle Street, London, N1 0XT\n"
        "   Phone: 020 7278 4400\n"
        "   Hours:\n"
        "     Monday - Saturday: 06:00 - 00:00\n"
        "     Sunday: 10:00 - 16:00\n"
        "   Services: Click & Collect, ATM, Self-Checkout\n"
        "   Click & Collect Cutoff: 22:00 previous day\n"
        "   Nearest Tube: Angel (Northern)\n"
    )

    return (
        "=== CUSTOMER ORDER CONTEXT ===\n"
        f"Customer: {customer['name']} (ID: {customer['id']})\n"
        f"Loyalty: {customer['loyalty_tier']} - {customer['loyalty_points']} Nectar points\n"
        f"Address: {customer['default_address']['line1']}, {customer['default_address']['city']}\n"
        "\nORDERS:\n"
        + "\n".join(orders_summary)
        + store_context
        + "\n\nAlways be helpful, warm, and solution-oriented. "
        f"Address the customer as {first_name}.\n"
        "Never fabricate order or store details. Only reference the data above.\n"
        "If asked about something not covered, say you will connect them with a specialist team.\n"
    )


# ---------------------------------------------------------------------------
# Agent Router
# ---------------------------------------------------------------------------

class AgentRouter:
    def __init__(self, customer_data: dict):
        self.customer_data = customer_data
        self.context       = build_context_block(customer_data)

        self._project_client: AIProjectClient | None = None
        self._openai_client: AzureOpenAI | None = None

        # Define database tools
        self._tools = [
            {
                "type": "function",
                "function": {
                    "name": "update_customer_address",
                    "description": "Updates the customer's default delivery address in the mock database.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "line1": {"type": "string", "description": "The street address, e.g. 50 Oak Lane"},
                            "city": {"type": "string", "description": "The city, e.g. London"},
                            "postcode": {"type": "string", "description": "The postcode, e.g. SW1A 1AA"}
                        },
                        "required": ["line1", "city"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "issue_refund",
                    "description": "Issues a refund for a spoiled or damaged item in a delivered order.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "order_id": {"type": "string", "description": "The order ID, e.g. ORD-98741"},
                            "reason": {"type": "string", "description": "The reason for the refund, e.g. Cheddar Cheese was mouldy"},
                            "amount": {"type": "number", "description": "The refund amount in GBP"},
                            "method": {"type": "string", "description": "The refund method, e.g. Original payment method or Nectar points"}
                        },
                        "required": ["order_id", "reason", "amount"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "check_stock",
                    "description": "Checks the stock levels, price, and aisle location of a product across stores.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "product_name": {"type": "string", "description": "The name or category of the product to search, e.g. milk, eggs, sourdough"},
                            "store_name": {"type": "string", "description": "Optional store name to check, e.g. Holborn or Islington"}
                        },
                        "required": ["product_name"]
                    }
                }
            }
        ]

        # intent -> Agent object from project
        self._intent_to_agent: dict[str, Any] = {}

        self._init_clients()

    # -----------------------------------------------------------------------
    # Database helper methods
    # -----------------------------------------------------------------------

    def _load_customer_data(self) -> dict:
        path = "C:\\Projects\\retail-chatbot\\mock_data\\customer.json"
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_customer_data(self, data: dict) -> None:
        path = "C:\\Projects\\retail-chatbot\\mock_data\\customer.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)



    def _load_inventory_data(self) -> dict:
        path = "C:\\Projects\\retail-chatbot\\mock_data\\inventory.json"
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_inventory_data(self, data: dict) -> None:
        path = "C:\\Projects\\retail-chatbot\\mock_data\\inventory.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def check_stock(self, product_name: str, store_name: str = None) -> str:
        try:
            data = self._load_inventory_data()
        except Exception as e:
            return f"Error loading inventory database: {e}"

        products = data.get("inventory", [])
        query = product_name.lower().strip()
        matched = []
        for p in products:
            if query in p["name"].lower() or query in p["category"].lower():
                matched.append(p)
                
        if not matched:
            return f"Product '{product_name}' was not found in our inventory."
            
        results = []
        for p in matched:
            lines = [
                f"Product: {p['name']}",
                f"  Price: GBP {p['price']:.2f}",
                f"  Category: {p['category']}",
                f"  Aisle: {p['aisle']}"
            ]
            
            stock_info = []
            stores_map = {
                "STR-001": "Sainsbury's Holborn",
                "STR-002": "Sainsbury's Islington"
            }
            
            if store_name:
                s_query = store_name.lower().strip()
                filtered_stock = {}
                for sid, sname in stores_map.items():
                    if s_query in sname.lower() or s_query in sid.lower():
                        filtered_stock[sid] = p["stock"].get(sid, 0)
                
                if not filtered_stock:
                    lines.append(f"  Stock: Store '{store_name}' not found.")
                else:
                    for sid, qty in filtered_stock.items():
                        sname = stores_map[sid]
                        status = "In Stock" if qty > 0 else "Out of Stock"
                        stock_info.append(f"{sname}: {qty} units ({status})")
                    lines.append("  Stock:\n    " + "\n    ".join(stock_info))
            else:
                for sid, qty in p["stock"].items():
                    sname = stores_map.get(sid, sid)
                    status = "In Stock" if qty > 0 else "Out of Stock"
                    stock_info.append(f"{sname}: {qty} units ({status})")
                lines.append("  Stock:\n    " + "\n    ".join(stock_info))
                
            results.append("\n".join(lines))
            
        return "\n\n".join(results)

    def update_customer_address(self, line1: str, city: str, postcode: str = None) -> str:
        data = self._load_customer_data()
        addr = data["customer"]["default_address"]
        addr["line1"] = line1
        addr["city"] = city
        if postcode:
            addr["postcode"] = postcode
        self._save_customer_data(data)
        return f"Address updated successfully to: {line1}, {city}"

    def issue_refund(self, order_id: str, reason: str, amount: float, method: str = "Original payment method") -> str:
        data = self._load_customer_data()
        order = next((o for o in data["orders"] if o["order_id"].lower() == order_id.lower()), None)
        if not order:
            return f"Error: Order {order_id} not found."
        
        import random
        ref_num = random.randint(20000, 99999)
        ref = f"REF-{ref_num}"
        
        from datetime import date
        today = date.today().isoformat()
        
        order["status"] = "refund_completed"
        order["refund"] = {
            "reason": reason,
            "requested_on": today,
            "amount": amount,
            "status": "completed",
            "method": method,
            "completed_on": today,
            "reference": ref
        }
        self._save_customer_data(data)
        return f"Refund issued successfully. Reference: {ref}, Amount: GBP{amount:.2f}"

    # -----------------------------------------------------------------------
    # Initialisation
    # -----------------------------------------------------------------------

    def _init_clients(self) -> None:
        api_key          = os.getenv("AZURE_AI_FOUNDRY_API_KEY",          "").strip()
        project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
        openai_endpoint  = os.getenv("AZURE_OPENAI_ENDPOINT",             "").strip()
        tenant_id        = os.getenv("AZURE_TENANT_ID",                   "").strip() or None

        # ------------------------------------------------------------------
        # AIProjectClient — AzureCliCredential
        # ------------------------------------------------------------------
        if project_endpoint:
            try:
                credential = AzureCliCredential(tenant_id=tenant_id)
                self._project_client = AIProjectClient(
                    endpoint=project_endpoint,
                    credential=credential,
                )
                print("[AgentRouter] AIProjectClient initialised [OK]")
                self._resolve_agents()
            except Exception as exc:
                print(f"[AgentRouter] AIProjectClient init failed: {exc}")
                self._project_client = None

        # ------------------------------------------------------------------
        # OpenAI client initialization
        # ------------------------------------------------------------------
        if self._project_client:
            try:
                self._openai_client = self._project_client.get_openai_client()
                print("[AgentRouter] OpenAI client initialised from Project Client [OK]")
            except Exception as exc:
                print(f"[AgentRouter] Failed to get OpenAI client from Project Client: {exc}")
                self._openai_client = None

        # Fallback to key-based AzureOpenAI client if client is not set
        if not self._openai_client and api_key and openai_endpoint:
            try:
                base = openai_endpoint.rstrip("/")
                if base.endswith("/v1"):
                    base = base[:-3]
                self._openai_client = AzureOpenAI(
                    api_key=api_key,
                    azure_endpoint=base,
                    api_version="2024-10-21",
                )
                print("[AgentRouter] AzureOpenAI client initialised using key-based fallback [OK]")
            except Exception as exc:
                print(f"[AgentRouter] AzureOpenAI key-based fallback init failed: {exc}")
                self._openai_client = None

        if not self._openai_client:
            print("[AgentRouter] WARNING: No OpenAI clients initialised. Check your .env file.")

    def _resolve_agents(self) -> None:
        """
        Discover agents by name from the new AI Foundry portal.
        """
        if not self._project_client:
            return

        try:
            all_agents = list(self._project_client.agents.list())
        except Exception as exc:
            print(
                f"[AgentRouter] list agents failed: {exc}\n"
                "  -> Run 'az login' in your terminal, then restart uvicorn.\n"
                "  -> Also ensure 'Azure AI Developer' role is assigned to your account."
            )
            return

        if not all_agents:
            print(
                "[AgentRouter] WARNING: list agents returned 0 agents.\n"
                "  -> Ensure agents exist in your new AI Foundry Portal -> Agents."
            )
            return

        # Map agent names/IDs
        name_to_agent = {a.name.lower(): a for a in all_agents}
        print(f"[AgentRouter] Discovered {len(all_agents)} agent(s):")
        for a in all_agents:
            print(f"  - {a.name!r}")

        for intent, (env_key, default_name) in AGENT_NAME_ENV_MAP.items():
            agent_val = os.getenv(env_key, default_name).strip()
            
            # Check for alternative ID environment variable (e.g. AZURE_AGENT_ORDER_ID)
            id_env_key = env_key.replace("_NAME", "_ID")
            id_val = os.getenv(id_env_key, "").strip()
            
            target_name = id_val if id_val else agent_val
            resolved_agent = name_to_agent.get(target_name.lower())
            
            if resolved_agent:
                self._intent_to_agent[intent] = resolved_agent
                print(f"[AgentRouter] Mapped '{intent}' -> '{resolved_agent.name}'")
            else:
                print(
                    f"[AgentRouter] WARNING: No agent named '{target_name}' found "
                    f"for intent '{intent}'.\n"
                    f"  Available agents: {list(name_to_agent.keys())}\n"
                    f"  Set {env_key} or {id_env_key} in .env to map this intent."
                )

    # -----------------------------------------------------------------------
    # -----------------------------------------------------------------------
    # Unified Chat Completion & Tool Execution Loop
    # -----------------------------------------------------------------------

    async def _call_chat_completion(
        self, messages_payload: list[dict], system_prompt: str, deployment: str
    ) -> str:
        # Run completion using the OpenAI client
        response = self._openai_client.chat.completions.create(
            model=deployment,
            messages=messages_payload,
            tools=self._tools,
            tool_choice="auto",
            max_tokens=600,
            temperature=0.0,
        )
        
        message_response = response.choices[0].message
        
        # Check if the model decided to call tools to update data
        if message_response.tool_calls:
            messages_payload.append(message_response)
            
            for tool_call in message_response.tool_calls:
                func_name = tool_call.function.name
                func_args = json.loads(tool_call.function.arguments)
                
                print(f"[AgentRouter] Executing tool: {func_name} with args: {func_args}")
                if func_name == "update_customer_address":
                    result = self.update_customer_address(
                        line1=func_args.get("line1"),
                        city=func_args.get("city"),
                        postcode=func_args.get("postcode")
                    )
                elif func_name == "issue_refund":
                    result = self.issue_refund(
                        order_id=func_args.get("order_id"),
                        reason=func_args.get("reason"),
                        amount=func_args.get("amount"),
                        method=func_args.get("method", "Original payment method")
                    )
                elif func_name == "check_stock":
                    result = self.check_stock(
                        product_name=func_args.get("product_name"),
                        store_name=func_args.get("store_name")
                    )
                else:
                    result = f"Error: Tool {func_name} not found."
                
                messages_payload.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": func_name,
                    "content": result
                })
            
            # Reload dynamically updated JSON and rebuild context prompt
            updated_customer = self._load_customer_data()
            updated_context = build_context_block(updated_customer)
            
            new_system_prompt = system_prompt.replace(self.context, updated_context)
            messages_payload[0]["content"] = new_system_prompt
            
            final_response = self._openai_client.chat.completions.create(
                model=deployment,
                messages=messages_payload,
                max_tokens=600,
                temperature=0.0
            )
            return final_response.choices[0].message.content.strip()
            
        return message_response.content.strip()

    async def _call_agent(
        self, agent: Any, message: str, history: list[dict]
    ) -> str:
        # Standard agent call - fetch system instructions from portal
        try:
            latest = agent.versions['latest']
            instructions = latest.definition['instructions']
        except Exception as exc:
            raise RuntimeError(f"Failed to retrieve instructions for agent '{agent.name}': {exc}")
        system_prompt = f"{instructions}\n\n{self.context}"
        
        # Build chat completions payload
        deployment = os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-4o").strip()
        messages_payload: list[dict] = [{"role": "system", "content": system_prompt}]
        for turn in history[-10:]:
            role    = turn.get("role", "user")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content:
                messages_payload.append({"role": role, "content": content})
        messages_payload.append({"role": "user", "content": message})

        return await self._call_chat_completion(messages_payload, system_prompt, deployment)

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

        # If fallback is triggered for refund, apply same strict instruction rules
        if intent == "refund":
            system_prompt = (
                "You are a Sainsbury's refund and returns specialist.\n"
                "STRICT RULES:\n"
                "1. Answer the user query ONLY using the Customer Order Context below.\n"
                "2. Do NOT use any external or general knowledge.\n"
                "3. Do NOT hallucinate or create refund rules under any circumstances.\n"
                "4. If the exact answer is not present in the Customer Order Context, you MUST say exactly: "
                "\"This information is not available in the refund policy documents.\"\n"
                "5. Never say anything else or make up policies if the information is missing.\n\n"
                f"{self.context}"
            )
        else:
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

        return await self._call_chat_completion(messages_payload, system_prompt, deployment)

    # -----------------------------------------------------------------------
    # Supervisor Agent Call
    # -----------------------------------------------------------------------

    async def _call_supervisor_agent(
        self, agent: Any, message: str, history: list[dict]
    ) -> str:
        if not self._openai_client:
            raise RuntimeError("OpenAI client is not initialised.")
        
        # Get the supervisor agent's version dynamically
        version_str = "latest"
        try:
            latest = agent.versions.get("latest") or agent.versions.latest
            if isinstance(latest, dict):
                version_str = latest.get("version", "latest")
            else:
                version_str = getattr(latest, "version", "latest")
        except Exception:
            pass
            
        # Build payload with conversation history
        messages_payload = []
        
        # Ground the supervisor agent with the Customer and Store context as the first turn
        messages_payload.append({
            "role": "user",
            "content": f"CUSTOMER AND STORE CONTEXT:\n{self.context}\nPlease load this context for the user session."
        })
        messages_payload.append({
            "role": "assistant",
            "content": "Understood. I have loaded the customer and store context. How can I help you today?"
        })
        
        # Add actual conversation history
        for turn in history[-10:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content:
                messages_payload.append({"role": role, "content": content})
                
        # Add current message
        messages_payload.append({"role": "user", "content": message})
        
        deployment = os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-4o").strip()
        
        # Call Supervisor Agent using responses.create with agent_reference
        res = self._openai_client.responses.create(
            model=deployment,
            input=messages_payload,
            extra_body={
                "agent_reference": {
                    "name": agent.name,
                    "version": version_str,
                    "type": "agent_reference",
                }
            }
        )
        
        if getattr(res, "output_text", None):
            return res.output_text
        raise RuntimeError("No output text returned from Supervisor Agent.")

    # -----------------------------------------------------------------------
    # Public handle
    # -----------------------------------------------------------------------

    async def handle(self, message: str, history: list[dict]) -> dict[str, Any]:
        # Reload mock JSON data dynamically on each request to make it fully dynamic
        customer_data = self._load_customer_data()
        self.context = build_context_block(customer_data)

        # Detect if the query is a profile mutation/action request (e.g. changing address or requesting a refund)
        # in which case we must skip the Supervisor Agent (RAG search on PDF only)
        # and route directly to intent sub-agents which support our local Python tools.
        msg_lower = message.lower()
        is_mutation_query = (
            (("address" in msg_lower or "postcode" in msg_lower) and any(w in msg_lower for w in ["change", "update", "new", "move", "edit", "modify", "different"]))
            or "moved" in msg_lower
            or any(w in msg_lower for w in ["refund", "return", "damaged", "spoiled", "mouldy", "broken", "expired", "past-use", "past use", "original payment method", "nectar points", "reimburse"])
        )

        # 1. Try querying the Supervisor Agent (RAG search on policy PDF) first for non-mutation queries
        supervisor_agent = self._intent_to_agent.get("supervisor")
        
        is_stock_query = any(w in msg_lower for w in ["stock", "available", "availability", "have", "do you have", "selling", "sell"])
        
        intent = classify_intent(message)
        reply = None
        strategy = None
        
        # 1. Try querying the Supervisor Agent (RAG search on uploaded documents) first for static non-mutation refund/store queries
        supervisor_agent = self._intent_to_agent.get("supervisor")
        if self._openai_client and supervisor_agent and intent in ("refund", "store") and not is_mutation_query and not is_stock_query:
            try:
                reply = await self._call_supervisor_agent(supervisor_agent, message, history)
                strategy = "supervisor_agent"
                
                # Check if the Supervisor Agent indicated the answer was not found in the documents
                refusal_phrases = [
                    "not available in the refund policy",
                    "not available in the documents",
                    "not available in the store details",
                    "do not contain",
                    "information is not available",
                    "cannot find this information",
                    "could not find any information",
                    "could not locate",
                    "not found",
                    "not listed",
                    "isn't listed",
                    "cannot find the address",
                    "could not find the address",
                    "no specific information",
                    "not explicitly mention"
                ]
                if any(p in reply.lower() for p in refusal_phrases) or "not available" in reply.lower() or "not find" in reply.lower():
                    print("[AgentRouter] >> Supervisor Agent could not find answer. Falling back to sub-agents...")
                    reply = None
            except Exception as exc:
                print(f"[AgentRouter] >> Supervisor Agent query failed: {exc}. Falling back to standard routing...")
                reply = None
        
        # 2. Fall back to intent-based sub-agents if supervisor couldn't answer or failed
        if reply is None:
            # Overrides for specific mutation queries to route to the correct sub-agent directly
            if is_mutation_query:
                if "address" in msg_lower or "moved" in msg_lower or "postcode" in msg_lower:
                    intent = "order"
                else:
                    intent = "refund"
                    
            agent = self._intent_to_agent.get(intent)
            
            if self._openai_client and agent:
                try:
                    reply = await self._call_agent(agent, message, history)
                    strategy = "foundry_agent"
                    print(f"[AgentRouter] >> Intent: '{intent}' | Agent: '{agent.name}' | Strategy: {strategy}")
                except Exception as exc:
                    print(f"[AgentRouter] >> Agent '{agent.name}' call failed: {exc} | Falling back to GPT-4o")
                    reply = await self._call_gpt4o_direct(intent, message, history)
                    strategy = "gpt4o_direct_fallback"
            else:
                reply = await self._call_gpt4o_direct(intent, message, history)
                strategy = "gpt4o_direct"
                print(f"[AgentRouter] >> No Foundry agent mapped | Intent: '{intent}' | Strategy: {strategy}")
        else:
            print(f"[AgentRouter] >> Resolved via Supervisor Agent RAG | Strategy: {strategy}")

        return {
            "reply":   reply,
            "intent":  intent,
            "sources": [strategy],
        }