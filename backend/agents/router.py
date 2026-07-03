"""
Retail AI Assistant – Main Orchestration and Routing Layer
"""

import os
import json
import re
import asyncio
import time
from typing import Any, Optional

from azure.identity import AzureCliCredential

import logging
logger = logging.getLogger(__name__)

# Constants used for out-of-scope declines
CHAT_DECLINE_MESSAGE  = "I'm sorry, I can only help with orders, deliveries, refunds, and store queries."
VOICE_DECLINE_MESSAGE = "Sorry, I can only help with shopping questions. Is there anything about your order or delivery I can help with?"

# Import validations
from .validation import (
    validate_and_sanitize_response,
    run_validation_layer,
    is_raw_routing_json,
)

# Import tool functions & helpers
from .tools import (
    build_context_block,
    check_stock,
    search_products,
    get_active_promotions,
    update_customer_address,
    issue_refund,
    append_product_grid_if_mentioned,
)

# ─────────────────────────────────────────────────────────────────────────────
# Agent Router – Orchestration Layer
# ─────────────────────────────────────────────────────────────────────────────

class AgentRouter:
    """
    Orchestrates Azure AI Foundry agents.
    No LLM prompts, instructions, or policies live here –
    those are configured inside Azure AI Foundry for each agent.
    """

    # Fast keyword sets for domain classification (no LLM call needed)
    _RETAIL_KEYWORDS: frozenset = frozenset([
        # Orders & delivery
        "order", "delivery", "deliver", "tracking", "track", "shipment", "dispatch",
        "parcel", "package", "arrive", "arrival", "slot", "reschedule", "address",
        "driver", "eta", "collected", "collect",
        # Refunds & returns
        "refund", "return", "exchange", "money back", "damaged", "broken",
        "spoil", "mould", "expired", "faulty",
        # Products & store
        "product", "item", "stock", "aisle", "shelf", "store", "branch",
        "availability", "available", "hours", "open", "close", "click and collect",
        # Food & nutrition
        "milk", "bread", "egg", "eggs", "chicken", "salmon", "cheese", "butter",
        "yoghurt", "yogurt", "pasta", "rice", "oat", "spinach", "avocado", "tomato",
        "juice", "water", "coffee", "tea", "chocolate", "biscuit", "snack",
        "cereal", "flour", "oil", "vinegar", "sauce", "soup",
        "calorie", "calories", "protein", "carb", "carbohydrate", "fat",
        "sugar", "fibre", "fiber", "sodium", "vitamin", "mineral", "nutrition",
        "nutritional", "allergen", "gluten", "lactose", "dairy", "vegan",
        "organic", "ingredient", "contains", "suitable", "intolerance",
        # Promotions & loyalty
        "promotion", "discount", "coupon", "offer", "deal", "code", "sale",
        "nectar", "points", "loyalty", "reward", "member", "gold", "platinum",
        # Electronics / non-food carried by Sainsbury's
        "kindle", "echo", "fitbit", "garmin", "headphone", "tracker", "electronics",
        "gadget", "tablet",
    ])

    _GENERAL_KEYWORDS: frozenset = frozenset([
        "who is", "what is the capital", "tell me about", "explain", "history of",
        "weather", "sport", "football", "cricket", "politics", "celebrity",
        "movie", "music", "song", "joke", "poem", "recipe", "cook",
        "programming", "python", "javascript", "code", "algorithm",
        "president", "prime minister", "war", "country", "planet", "space",
    ])

    _ACKNOWLEDGEMENTS: frozenset = frozenset([
        "yes", "yeah", "yep", "yup", "sure", "okay", "ok", "alright", "sounds good",
        "go ahead", "continue", "next", "show me", "tell me more", "more",
        "thats fine", "that's fine", "do it", "proceed", "exactly", "correct", "right",
        "this one", "that one", "first one", "second one"
    ])

    _DIRECT_ROUTING_KEYWORDS = {
        "refund": [
            "refund", "return", "money back", "damaged", "broken", "spoil",
            "mould", "expired", "faulty", "cashback", "reimburse", "compensation"
        ],
        "delivery": [
            "delivery", "deliver", "tracking", "track", "shipment", "dispatch",
            "parcel", "package", "arrive", "arrival", "slot", "reschedule", "address",
            "driver", "eta", "van", "postcode", "slots", "when will it arrive", "live tracking"
        ],
        "store": [
            "store", "branch", "hours", "open", "close", "stock", "aisle", "shelf",
            "availability", "available", "promotion", "discount", "coupon", "offer", "deal", "sale",
            "nectar", "points", "loyalty", "reward", "gluten", "vegan", "organic", "ingredient",
            "contains", "suitable", "nutrition", "nutritional", "calorie", "calories", "protein",
            "carb", "carbohydrate", "fat", "sugar", "allergen", "allergens", "in stock", "out of stock"
        ],
        "order": [
            "order", "payment", "buy", "purchase", "receipt", "charge", "card", "pay",
            "nectar points", "balance", "cost", "price", "how much is", "ordered", "recent orders"
        ]
    }

    # Bind imported validation and sanitization functions as instance delegation helper methods
    async def _run_validation_layer(self, query: str, reply: str) -> str:
        return await run_validation_layer(query, reply)

    def _is_raw_routing_json(self, text: str) -> bool:
        return is_raw_routing_json(text)

    # Bind imported tool functions
    check_stock = check_stock
    search_products = search_products
    get_active_promotions = get_active_promotions
    update_customer_address = update_customer_address
    issue_refund = issue_refund
    append_product_grid_if_mentioned = append_product_grid_if_mentioned

    def _get_direct_routing_tasks(self, message: str) -> Optional[list[dict]]:
        text = message.lower()
        
        # Check transition words that suggest multiple actions or a complex query
        if any(w in text for w in [" and ", " also ", " then ", " but ", " as well ", " addition "]):
            return None
            
        matched_agents = []
        for agent_type, keywords in self._DIRECT_ROUTING_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                matched_agents.append(agent_type)
                
        # Only return tasks if exactly one agent is matched
        if len(matched_agents) == 1:
            return [{"agent": matched_agents[0], "task_query": message}]
            
        return None

    def __init__(self, customer_data: dict):
        self.customer_data = customer_data
        self.context = build_context_block(customer_data)
        self._openai_client = None          # from AIProjectClient.get_openai_client()
        self._project_client = None         # AIProjectClient instance
        self._async_openai_client = None
        # Maps logical role → Foundry asst_* agent ID (resolved at startup)
        self._agent_ids: dict[str, Optional[str]] = {
            "supervisor": None,
            "order":      None,
            "delivery":   None,
            "refund":     None,
            "store":      None,
            "general":    None,
        }
        self._init_clients()
        self._resolve_agent_ids()

        # ── Tool schemas (implementations live in this class; Foundry calls them) ──
        self._tools_order = [
            {
                "type": "function",
                "function": {
                    "name": "search_products",
                    "description": (
                        "Searches and filters the product catalog using criteria like "
                        "name/query, category, dietary tags (organic, vegan, gluten_free, "
                        "sugar_free, high_protein, lactose_free, healthy_choice), "
                        "promotions, and custom sorting."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search term, e.g. milk, eggs, sourdough"},
                            "category": {"type": "string", "description": "Product category, e.g. Dairy, Bakery, Produce"},
                            "dietary_filters": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": ["organic", "vegan", "gluten_free", "sugar_free",
                                             "high_protein", "lactose_free", "healthy_choice"]
                                },
                                "description": "List of dietary/health filters"
                            },
                            "sort_by": {
                                "type": "string",
                                "enum": ["price_asc", "price_desc", "rating", "popularity"]
                            },
                            "best_seller":       {"type": "boolean"},
                            "store_recommended": {"type": "boolean"},
                            "is_on_promotion":   {"type": "boolean"},
                            "store_name":        {"type": "string"},
                            "limit":             {"type": "integer"},
                        },
                    },
                },
            }
        ]

        self._tools_delivery = [
            {
                "type": "function",
                "function": {
                    "name": "update_customer_address",
                    "description": "Updates the customer's default delivery address in the database.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "line1":     {"type": "string"},
                            "city":      {"type": "string"},
                            "postcode":  {"type": "string"},
                        },
                        "required": ["line1", "city"],
                    },
                },
            }
        ]

        self._tools_refund = [
            {
                "type": "function",
                "function": {
                    "name": "issue_refund",
                    "description": "Issues a refund for a spoiled or damaged item in a delivered order.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "order_id": {"type": "string"},
                            "reason":   {"type": "string"},
                            "amount":   {"type": "number"},
                            "method":   {"type": "string"},
                        },
                        "required": ["order_id", "reason", "amount"],
                    },
                },
            }
        ]

        self._tools_store = [
            {
                "type": "function",
                "function": {
                    "name": "check_stock",
                    "description": "Checks stock levels, price, and aisle of a product across stores.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "product_name": {"type": "string"},
                            "store_name":   {"type": "string"},
                        },
                        "required": ["product_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_active_promotions",
                    "description": "Retrieves the list of active store promotions and discount coupon codes.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

        # Map agent type → tool list (used when passing tools at run-creation time)
        self._agent_tools: dict[str, list] = {
            "order":    self._tools_order,
            "delivery": self._tools_delivery,
            "refund":   self._tools_refund,
            "store":    self._tools_store,
            "general":  [],
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Client Initialisation
    # ─────────────────────────────────────────────────────────────────────────

    def _init_clients(self) -> None:
        project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
        tenant_id        = os.getenv("AZURE_TENANT_ID", "").strip() or None
        api_key          = os.getenv("AZURE_AI_FOUNDRY_API_KEY", "").strip()
        openai_endpoint  = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()

        is_serverless = os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME")

        # ── Primary: AIProjectClient (new Azure AI Foundry SDK) ──────────────
        if project_endpoint:
            try:
                from azure.ai.projects import AIProjectClient
                if is_serverless:
                    from azure.identity import DefaultAzureCredential
                    credential = DefaultAzureCredential()
                    cred_name = "DefaultAzureCredential"
                else:
                    credential = AzureCliCredential(tenant_id=tenant_id)
                    cred_name = "AzureCliCredential"

                self._project_client = AIProjectClient(
                    endpoint=project_endpoint,
                    credential=credential,
                )
                # Get the OpenAI-compatible client from the project
                self._openai_client = self._project_client.get_openai_client()
                print(f"[AgentRouter] AIProjectClient initialised via {cred_name}.")
                print(f"[AgentRouter] OpenAI base URL: {self._openai_client.base_url}")
            except Exception as e:
                print(f"[AgentRouter] AIProjectClient init failed: {e}")

        # ── Fallback: Direct AzureOpenAI (for non-Foundry calls if needed) ───
        if not self._openai_client and api_key and openai_endpoint:
            try:
                from urllib.parse import urlparse
                from openai import AzureOpenAI
                parsed = urlparse(openai_endpoint)
                base = f"{parsed.scheme}://{parsed.netloc}"
                self._openai_client = AzureOpenAI(
                    api_key=api_key,
                    azure_endpoint=base,
                    api_version="2024-10-21",
                )
                print(f"[AgentRouter] Fallback AzureOpenAI client initialised on base: {base}")
            except Exception as e:
                print(f"[AgentRouter] AzureOpenAI fallback init failed: {e}")

    def _resolve_agent_ids(self) -> None:
        """
        In the new Azure AI Foundry SDK, agents are invoked by NAME using
        agent_reference. We verify the expected agents exist in the project
        and build a role -> agent_name map.
        """
        # Build role -> agent_name map from env vars
        name_map = {
            "supervisor":         os.getenv("AZURE_AGENT_SUPERVISOR_NAME",  "Supervisor-Agent"),
            "order":              os.getenv("AZURE_AGENT_ORDER_NAME",       "Order-Agent"),
            "delivery":           os.getenv("AZURE_AGENT_DELIVERY_NAME",    "Delivery-Agent"),
            "refund":             os.getenv("AZURE_AGENT_REFUND_NAME",      "Refund-Agent"),
            "store":              os.getenv("AZURE_AGENT_STORE_NAME",       "Store-Agent"),
            "general":            os.getenv("AZURE_AGENT_GENERAL_NAME",     "General-Assistant-Agent"),
            "intent_classifier":  os.getenv("AZURE_AGENT_INTENT_NAME",     "Intent-Classifier-Agent"),
            "context_resolver":   os.getenv("AZURE_AGENT_CONTEXT_NAME",    "Context-Resolver-Agent"),
            "suggestions":        os.getenv("AZURE_AGENT_SUGGESTIONS_NAME","Suggestions-Agent"),
            "voice_assistant":    os.getenv("AZURE_AGENT_VOICE_NAME",      "Voice-Assistant-Agent"),
        }

        # In new Foundry SDK, agent_ids stores the agent NAME (used in agent_reference)
        for role, agent_name in name_map.items():
            self._agent_ids[role] = agent_name

        # Verify agents exist via AIProjectClient if available
        if self._project_client:
            try:
                logger.info("[AgentRouter] Verifying agents in AI Foundry project...")
                agents = list(self._project_client.agents.list())
                available_names = {a.name for a in agents}
                logger.info("[AgentRouter] Found %d agents: %s", len(available_names), sorted(available_names))

                required_roles = ["supervisor", "order", "delivery", "refund", "store", "general"]
                for role in required_roles:
                    agent_name = name_map[role]
                    if agent_name in available_names:
                        logger.info("[AgentRouter]   %-18s '%s' -> VERIFIED", role + ":", agent_name)
                    else:
                        logger.warning(
                            "[AgentRouter]   %-18s '%s' -> NOT FOUND in project (agents may still be provisioning)",
                            role + ":", agent_name
                        )

                # Optional roles
                for role in ["intent_classifier", "context_resolver", "suggestions", "voice_assistant"]:
                    agent_name = name_map[role]
                    if agent_name in available_names:
                        logger.info("[AgentRouter]   %-18s '%s' -> VERIFIED (optional)", role + ":", agent_name)
                    else:
                        logger.warning("[AgentRouter]   Optional role '%s' agent '%s' not found.", role, agent_name)

                logger.info("[AgentRouter] Agent resolution complete.")
            except Exception as e:
                logger.warning("[AgentRouter] Agent verification failed: %s. Will proceed with name-based invocation.", e)

    def _load_customer_data(self) -> dict:
        from database import load_db_customer_data
        return load_db_customer_data()

    def _save_customer_data(self, data: dict) -> None:
        from database import save_db_customer_data
        save_db_customer_data(data)

    def _load_inventory_data(self) -> dict:
        from database import load_db_inventory_data
        return load_db_inventory_data()

    # ─────────────────────────────────────────────────────────────────────────
    # Tool Dispatcher (called during Foundry run requires_action handling)
    # ─────────────────────────────────────────────────────────────────────────

    def _execute_tool(self, func_name: str, func_args: dict) -> str:
        """Dispatch a Foundry tool call to the appropriate local implementation."""
        print(f"[AgentRouter] Tool call: {func_name}({func_args})")
        try:
            if func_name == "search_products":
                return self.search_products(
                    query=func_args.get("query"),
                    category=func_args.get("category"),
                    dietary_filters=func_args.get("dietary_filters"),
                    sort_by=func_args.get("sort_by"),
                    best_seller=func_args.get("best_seller"),
                    store_recommended=func_args.get("store_recommended"),
                    is_on_promotion=func_args.get("is_on_promotion"),
                    store_name=func_args.get("store_name"),
                    limit=func_args.get("limit"),
                )
            elif func_name == "check_stock":
                return self.check_stock(
                    product_name=func_args.get("product_name"),
                    store_name=func_args.get("store_name"),
                )
            elif func_name == "get_active_promotions":
                return self.get_active_promotions()
            elif func_name == "issue_refund":
                return self.issue_refund(
                    order_id=func_args.get("order_id"),
                    reason=func_args.get("reason"),
                    amount=func_args.get("amount"),
                    method=func_args.get("method", "Original payment method"),
                )
            elif func_name == "update_customer_address":
                return self.update_customer_address(
                    line1=func_args.get("line1"),
                    city=func_args.get("city"),
                    postcode=func_args.get("postcode"),
                )
            else:
                return f"Error: Unknown tool '{func_name}'."
        except Exception as e:
            return f"Error executing tool '{func_name}': {e}"

    # ─────────────────────────────────────────────────────────────────────────
    # Domain Classification
    # ─────────────────────────────────────────────────────────────────────────

    def _classify_domain(self, message: str, history: list[dict], is_voice: bool = False) -> str:
        """
        Returns 'retail' or 'general'.
        """
        text_lower = message.lower()

        # For voice calls, bypass LLM domain classification to guarantee sub-1.5s latency.
        # Default to 'retail' unless clear general indicators are matched.
        if is_voice:
            if any(kw in text_lower for kw in self._GENERAL_KEYWORDS):
                return "general"
            return "retail"

        # 1. Retail keyword match
        if any(kw in text_lower for kw in self._RETAIL_KEYWORDS):
            return "retail"

        # 2. Clear general-knowledge indicators
        if any(kw in text_lower for kw in self._GENERAL_KEYWORDS):
            return "general"

        # 3. LLM fallback for genuinely ambiguous messages
        if self._openai_client:
            deployment = os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-4o")
            try:
                res = self._openai_client.chat.completions.create(
                    model=deployment,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                            "You are a domain classifier for a Sainsbury's retail assistant.\n"
                            "Respond with ONE word only: 'retail' or 'general'.\n"
                            "retail = orders, delivery, refunds, products, store, grocery.\n"
                            "general = anything not related to retail shopping."
                        ),
                        },
                        {"role": "user", "content": message},
                    ],
                    max_completion_tokens=5,
                    temperature=0.0,
                )
                label = res.choices[0].message.content.strip().lower()
                if label in ("retail", "general"):
                    return label
            except Exception as e:
                print(f"[AgentRouter] Domain classification LLM call failed: {e}")

        # 4. Safe default
        return "retail"

    def _classify_intent(self, message: str, history: list[dict], is_voice: bool = False) -> str:
        """
        Classifies the intent of the message in the context of the conversation history.
        """
        # For voice calls, bypass LLM intent classification to guarantee sub-1.5s latency.
        # Check acknowledgements first, then fallback to voice-optimized domain classification.
        if is_voice:
            cleaned = re.sub(r'[^\w\s]', '', message).lower().strip()
            if cleaned in self._ACKNOWLEDGEMENTS:
                return "clarification_confirmation"
            domain = self._classify_domain(message, history, is_voice)
            return "new_retail" if domain == "retail" else "new_general"

        # First check if there is conversation history
        assistant_turns = [t for t in history if t.get("role") == "assistant"]
        if not assistant_turns:
            # No history: must be a new request
            domain = self._classify_domain(message, history, is_voice)
            return "new_retail" if domain == "retail" else "new_general"

        # Check local exact-match acknowledgements list first
        cleaned = re.sub(r'[^\w\s]', '', message).lower().strip()
        if cleaned in self._ACKNOWLEDGEMENTS:
            return "clarification_confirmation"

        # If LLM client is available, run intent classification using LLM
        if self._openai_client:
            deployment = os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-4o")
            try:
                history_snippet = "\n".join(
                    f"{t['role'].upper()}: {t['content']}"
                    for t in history[-5:]
                )
                res = self._openai_client.chat.completions.create(
                    model=deployment,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                            "Classify the user's intent in a retail chatbot conversation.\n"
                            "Respond with ONE label only:\n"
                            "  follow_up - references previous exchange (it, that, same, etc.)\n"
                            "  clarification_confirmation - yes/no/sure/ok confirming a suggestion\n"
                            "  new_retail - new retail question (order, product, delivery, etc.)\n"
                            "  new_general - unrelated to retail"
                        ),
                        },
                        {
                            "role": "user",
                            "content": f"CONVERSATION HISTORY:\n{history_snippet}\n\nUSER MESSAGE: {message}"
                        }
                    ],
                    max_completion_tokens=10,
                    temperature=0.0,
                )
                label = res.choices[0].message.content.strip().lower()
                # Clean up punctuation from label
                label = re.sub(r'[^\w\-]', '', label)
                if label in ("follow_up", "clarification_confirmation", "new_retail", "new_general"):
                    return label
            except Exception as e:
                print(f"[AgentRouter] Intent classification LLM call failed: {e}")

        # Fallback to domain classification
        domain = self._classify_domain(message, history, is_voice)
        return "new_retail" if domain == "retail" else "new_general"

    def _is_out_of_context(self, message: str) -> bool:
        """
        Uses direct AzureOpenAI to evaluate if the message is out of context.
        """
        if not self._openai_client:
            return False  # safe default: do not block if client is not configured
        
        deployment = os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-4o")
        try:
            res = self._openai_client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": (
                        "You are a guardrail classifier for a Sainsbury's retail chatbot.\n"
                        "Respond with exactly one word: ALLOWED or BLOCKED.\n"
                        "ALLOWED: orders, delivery, refunds, store info, products, groceries, shopping.\n"
                        "BLOCKED: anything unrelated to retail shopping (politics, coding, jokes, etc)."
                    )},
                    {"role": "user", "content": message}
                ],
                max_completion_tokens=5,
                temperature=0.0,
            )
            decision = res.choices[0].message.content.strip().upper()
            print(f"[AgentRouter][GUARDRAIL] Query: '{message}' | Decision: {decision}")
            return decision == "BLOCKED"
        except Exception as e:
            print(f"[AgentRouter][GUARDRAIL] Guardrail check failed: {e}")
            return False

    async def _resolve_context(self, message: str, history: list[dict]) -> dict[str, Any]:
        """
        Resolves a follow-up or clarification message using the conversation history.
        """
        # Find the last assistant message
        assistant_turns = [t for t in history if t.get("role") == "assistant"]
        prev_assistant = assistant_turns[-1]["content"] if assistant_turns else ""

        if self._openai_client:
            deployment = os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-4o")
            try:
                history_snippet = "\n".join(
                    f"{t['role'].upper()}: {t['content']}"
                    for t in history[-5:]
                )
                system_prompt = (
                    "You are the Context Resolver for a Sainsbury's retail chatbot.\n"
                    "The user has sent a follow-up or clarification message to the previous assistant response.\n\n"
                    f"Previous Assistant Response:\n\"{prev_assistant}\"\n\n"
                    "Your job is to analyze the history and decide between two output types:\n\n"
                    "1. CLARIFICATION:\n"
                    "If the previous assistant response offered multiple choices or actions "
                    "(e.g., 'delivery or Click & Collect', 'directions or online ordering', 'directions or ordering online'), "
                    "AND the user's current reply is a generic confirmation/acknowledgement ('yes', 'yeah', 'ok', 'sure', etc.) "
                    "that does not specify which choice they want: "
                    "You MUST generate a targeted clarification response asking the user to specify their choice.\n"
                    "Rules for clarification response:\n"
                    "- Do NOT make assumptions about which option they want.\n"
                    "- Respond politely and directly ask which option they prefer.\n"
                    "Output JSON format:\n"
                    "{\n"
                    "  \"type\": \"clarification\",\n"
                    "  \"response\": \"<your targeted clarification response>\"\n"
                    "}\n\n"
                    "2. RESOLVED QUERY:\n"
                    "If the user's message is a follow-up question, or if they have specified their choice "
                    "(e.g., 'first one', 'delivery', 'online'), or if only one option or action was offered,\n"
                    "or if the previous question was a simple yes/no query (e.g. 'Would you like to check the price?'):\n"
                    "You MUST output a RESOLVED QUERY. Do NOT generate a CLARIFICATION for a yes/no question when the user answers 'sure', 'yes', 'ok', etc.\n"
                    "Resolve the user's message into a standalone, complete, detail-rich retail search/intent query "
                    "that combines the current user message with all necessary details from the history (like product name, "
                    "order ID, store location) so it can be processed independently by the supervisor/specialist agents.\n"
                    "Output JSON format:\n"
                    "{\n"
                    "  \"type\": \"resolved_query\",\n"
                    "  \"query\": \"<standalone resolved retail query>\"\n"
                    "}\n\n"
                    "Return ONLY valid JSON. No explanations, no markdown formatting, no code blocks."
                )

                res = self._openai_client.chat.completions.create(
                    model=deployment,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"CONVERSATION HISTORY:\n{history_snippet}\n\nUSER MESSAGE: {message}"}
                    ],
                    max_completion_tokens=150,
                    temperature=0.0,
                )
                content = res.choices[0].message.content.strip()
                # Strip markdown JSON fences if present
                clean = re.sub(r"^```(?:json)?\n?", "", content)
                clean = re.sub(r"\n?```$", "", clean)
                data = json.loads(clean)
                if isinstance(data, dict) and "type" in data:
                    if data["type"] == "clarification" and "response" in data:
                        return data
                    if data["type"] == "resolved_query" and "query" in data:
                        return data
            except Exception as e:
                print(f"[AgentRouter] Context resolution LLM call failed: {e}")

        # Fallback if LLM fails or returns invalid response:
        return {
            "type": "resolved_query",
            "query": message
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Product DB Lookup (for product-info questions)
    # ─────────────────────────────────────────────────────────────────────────

    # Keywords that signal a product-info question (nutrition, allergens, etc.)
    _PRODUCT_INFO_SIGNALS = frozenset([
        "how much protein", "how many calories", "calorie", "calories",
        "protein", "carbs", "carbohydrate", "fat", "sugar", "fibre",
        "fiber", "sodium", "vitamins", "nutritional", "nutrition",
        "allergen", "contains gluten", "contain gluten", "gluten free",
        "wheat free", "dairy free", "lactose", "nut free", "allergy",
        "ingredient", "ingredients", "suitable for vegan", "is it vegan",
        "is it organic", "healthy", "is this healthy", "calories per",
        "per 100g", "per serving",
    ])

    def _search_db_for_product_question(self, message: str) -> Optional[str]:
        """
        If the message is a product-info question (nutrition/allergens/etc.),
        search retail_chatbot.db and return a formatted catalog card.
        """
        text_lower = message.lower()

        # Only activate for product-info style questions
        if not any(signal in text_lower for signal in self._PRODUCT_INFO_SIGNALS):
            return None

        # Extract candidate product terms from the message
        # Look for known nouns + any multi-word capitalised phrases
        candidate_terms = []

        # Common product mentions
        known_products = [
            "egg", "eggs", "milk", "oat milk", "almond milk", "soy milk",
            "bread", "sourdough", "porridge", "oats", "porridge oats",
            "chicken", "salmon", "cheese", "cheddar", "butter", "yoghurt",
            "yogurt", "pasta", "spinach", "avocado", "tomato", "juice",
            "orange juice", "coffee", "tea", "chocolate", "biscuit",
            "cereal", "rice", "flour", "oil", "olive oil", "cream",
        ]
        for prod in known_products:
            if prod in text_lower:
                candidate_terms.append(prod)

        # Also try to extract quoted or capitalised product names
        quoted = re.findall(r'"([^"]+)"', message)
        candidate_terms.extend(quoted)

        if not candidate_terms:
            return None

        try:
            data     = self._load_inventory_data()
            products = data.get("inventory", [])
        except Exception:
            return None

        found_products = []
        for term in candidate_terms:
            term_lower = term.lower()
            for p in products:
                name_lower = p["name"].lower()
                if term_lower in name_lower or name_lower in term_lower:
                    if p not in found_products:
                        found_products.append(p)

        if not found_products:
            # Product-info question but product not in our catalog
            term_display = candidate_terms[0] if candidate_terms else "that product"
            return (
                f"I searched our product catalog for **{term_display}** but it is not "
                f"currently available in our Sainsbury's range. I can only provide "
                f"nutritional and allergen information for products we stock. "
                f"You can browse our full range at https://www.sainsburys.co.uk/."
            )

        # Build catalog cards with nutritional + allergen info
        cards = []
        for p in found_products[:3]:  # cap at 3 to avoid wall of text
            nutritional = p.get("nutritional_info", {})
            allergens   = p.get("allergens", [])
            total_qty   = sum(sinfo.get("quantity", 0) for sinfo in p.get("stock", {}).values())
            avail       = ("Out of Stock" if total_qty == 0
                           else ("Limited Availability" if total_qty <= 8 else "In Stock"))
            disc        = p.get("discount", {})
            offer_str   = f"  • On Sale: {disc['offer_text']}" if disc.get("is_on_sale") else ""

            _brand = p.get('brand', "Sainsbury's")
            card_lines = [
                f"**{p['name']}** – {_brand}",
                f"  • Price: £{p['price']:.2f}",
                f"  • Availability: {avail}",
                f"  • Rating: {p.get('customer_rating', 4.0):.1f}/5 "
                  f"({p.get('review_count', 0):,} reviews)",
            ]
            if offer_str:
                card_lines.append(offer_str)

            if nutritional:
                card_lines.append("  • Nutritional Info (per 100g):")
                for k, v in nutritional.items():
                    card_lines.append(f"      – {k}: {v}")

            if allergens:
                card_lines.append(f"  • Allergens: {', '.join(allergens)}")
            else:
                card_lines.append("  • Allergens: None listed")

            diet_tags = p.get("diet_tags", [])
            if diet_tags:
                card_lines.append(f"  • Dietary Tags: {', '.join(diet_tags)}")

            cards.append("\n".join(card_lines))

        return (
            f"Here is the information from our product catalog:\n\n"
            + "\n\n".join(cards)
            + "\n\nFor full nutritional details and to shop online, visit "
              "https://www.sainsburys.co.uk/."
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Foundry Agent Invocation (Thread → Message → Run → Poll → Tool Calls)
    # ─────────────────────────────────────────────────────────────────────────

    async def _call_foundry_agent(
        self,
        agent_id: str,          # In new Foundry SDK, this is the agent NAME
        context: str,
        task_query: str,
        history: list[dict],
        extra_instructions: str = "",
    ) -> str:
        """
        Invokes a single Azure AI Foundry agent using the reference pattern:
        AIProjectClient → get_openai_client() → conversations + responses API.
        The agent_id parameter holds the agent NAME (e.g. 'Order-Agent').
        """
        if not self._openai_client:
            raise RuntimeError("OpenAI client not initialised.")

        agent_name = agent_id   # In the new SDK, we call agents by name
        logger.info("[AgentRouter] === AZURE AI FOUNDRY AGENT INVOCATION ===")
        logger.info("[AgentRouter] Agent: %s | Query: %s", agent_name, task_query[:150])

        loop = asyncio.get_event_loop()
        t_start = time.perf_counter()

        # Build full input: inject context + history + task_query
        messages_input = []
        if context:
            messages_input.append({"role": "system", "content": context})
        if extra_instructions:
            messages_input.append({"role": "system", "content": extra_instructions})
        for turn in history[-6:]:
            role    = turn.get("role", "user")
            content = turn.get("content", "").strip()
            if role in ("user", "assistant") and content:
                messages_input.append({"role": role, "content": content})
        messages_input.append({"role": "user", "content": task_query})

        # Flatten to a single string input for responses API
        full_input = "\n\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in messages_input
        )

        # Call agent via responses API with agent_reference
        def _call():
            return self._openai_client.responses.create(
                input=full_input,
                extra_body={
                    "agent_reference": {
                        "name": agent_name,
                        "type": "agent_reference",
                    }
                },
            )

        try:
            response = await loop.run_in_executor(None, _call)
        except Exception as e:
            # Fallback: try without extra_body (some SDK versions handle it differently)
            logger.warning("[AgentRouter] responses.create with agent_reference failed: %s. Retrying without extra_body.", e)
            def _call_plain():
                return self._openai_client.responses.create(
                    model=agent_name,
                    input=full_input,
                )
            response = await loop.run_in_executor(None, _call_plain)

        t_done = time.perf_counter() - t_start
        reply = getattr(response, "output_text", None) or str(response)
        logger.info("[AgentRouter] Agent '%s' replied in %.2fs. Length: %d", agent_name, t_done, len(reply))
        return reply

    async def _decompose_via_supervisor(
        self, message: str, history: list[dict]
    ) -> list[dict]:
        """
        Calls the Foundry Supervisor-Agent with the user message.
        """
        supervisor_id = self._agent_ids.get("supervisor")
        history_snippet = "\n".join(
            f"{t['role'].upper()}: {t['content']}"
            for t in history[-5:]
        )

        if supervisor_id and self._openai_client:
            # Build a structured routing request for the Supervisor-Agent
            routing_request = (
                f"CONVERSATION HISTORY:\n{history_snippet}\n\n"
                f"CURRENT USER MESSAGE: {message}\n\n"
                "Decompose this into routing tasks. "
                "Respond ONLY with a valid JSON array of objects with 'agent' and 'task_query' keys. "
                "Available agents: order, delivery, refund, store. "
                "No markdown, no explanation."
            )
            try:
                raw = await self._call_foundry_agent(
                    agent_id=supervisor_id,
                    context=self.context,
                    task_query=routing_request,
                    history=[],
                )
                # Strip markdown code fences if present
                clean = re.sub(r"^```(?:json)?\n?", "", raw.strip())
                clean = re.sub(r"\n?```$", "", clean)
                tasks = json.loads(clean)
                if (
                    isinstance(tasks, list)
                    and all("agent" in t and "task_query" in t for t in tasks)
                ):
                    print(f"[AgentRouter] Supervisor routing: {tasks}")
                    return tasks
            except Exception as e:
                print(f"[AgentRouter] Supervisor routing failed: {e}. Using fallback.")

        # Direct LLM fallback if Supervisor Agent is not in Foundry but OpenAI client is available
        if self._openai_client:
            routing_prompt = (
            "You are the Supervisor Agent for a Sainsbury's retail AI assistant.\n"
            "Analyse the user request and return a JSON array of tasks to route to specialist agents.\n"
            "Available agents: order, delivery, refund, store, general.\n"
            "Return ONLY valid JSON. Example: [{\"agent\": \"order\", \"task_query\": \"track order 123\"}]"
        )
            try:
                deployment = os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-4o")
                loop = asyncio.get_event_loop()
                def call_routing():
                    return self._openai_client.chat.completions.create(
                        model=deployment,
                        messages=[
                            {"role": "system", "content": routing_prompt},
                            {"role": "user", "content": message}
                        ],
                        max_completion_tokens=300,
                        temperature=0.0,
                    )
                res = await loop.run_in_executor(None, call_routing)
                content = res.choices[0].message.content.strip()
                clean = re.sub(r"^```(?:json)?\n?", "", content)
                clean = re.sub(r"\n?```$", "", clean)
                tasks = json.loads(clean)
                if (
                    isinstance(tasks, list)
                    and all("agent" in t and "task_query" in t for t in tasks)
                ):
                    print(f"[AgentRouter] Supervisor direct LLM routing fallback: {tasks}")
                    return tasks
            except Exception as e:
                print(f"[AgentRouter] Supervisor direct LLM routing fallback failed: {e}")

        # Keyword fallback
        intent = self._classify_fallback(message)
        return [{"agent": intent, "task_query": message}]

    def _classify_fallback(self, message: str) -> str:
        """Keyword-based routing fallback (no LLM call). Covers broad spoken query patterns."""
        text = message.lower()

        # General / Greetings / Small Talk
        if any(kw in text for kw in self._GENERAL_KEYWORDS):
            return "general"

        # Refund / Returns
        if any(w in text for w in [
            "refund", "return", "money back", "damaged", "broken",
            "spoil", "mould", "expire", "compensation", "reimburse",
            "get my money", "want my money", "credit", "receipt",
        ]):
            return "refund"

        # Delivery / Tracking
        if any(w in text for w in [
            "delivery", "deliver", "track", "tracking", "where is my",
            "where's my", "when will it", "arriving", "arrived", "arrive",
            "eta", "driver", "van", "slot", "reschedule", "change address",
            "live tracking", "on its way", "out for delivery", "estimated",
            "shipping", "shipment", "courier", "dispatch", "parcel",
        ]):
            return "delivery"

        # Store / Products / Promotions
        if any(w in text for w in [
            "store", "shop", "branch", "open", "hours", "timings", "location",
            "stock", "availability", "product", "item", "range", "aisle",
            "price", "cost", "how much", "recommend", "suggest", "suggest",
            "allergen", "gluten", "vegan", "organic", "dairy", "nutrition",
            "calories", "protein", "carbs", "sugar", "fibre", "ingredients",
            "promotion", "discount", "coupon", "offer", "deal", "sale",
            "click and collect", "collect", "pickup", "click", "buy",
        ]):
            return "store"

        # Orders — default retail fallback
        return "order"

    # ─────────────────────────────────────────────────────────────────────────
    # Multi-Agent Reply Merge
    # ─────────────────────────────────────────────────────────────────────────

    async def _merge_replies(
        self, message: str, tasks: list[dict], replies: list[str]
    ) -> str:
        """
        Single-agent replies are returned as-is.
        Multi-agent replies are merged via the Foundry Supervisor-Agent
        or via a lightweight local concatenation fallback.
        """
        if len(replies) == 1:
            return replies[0]

        supervisor_id = self._agent_ids.get("supervisor")
        merge_request = f"Original customer question: {message}\n\n"
        for i, (task, reply) in enumerate(zip(tasks, replies), 1):
            merge_request += f"--- Part {i} (Agent: {task['agent']}) ---\n{reply}\n\n"
        merge_request += (
            "Merge these specialist replies into a single, cohesive, "
            "well-formatted customer response. "
            "Keep all important details. No duplicate greetings or sign-offs."
        )

        if supervisor_id and self._openai_client:
            try:
                merged = await self._call_foundry_agent(
                    agent_id=supervisor_id,
                    context=self.context,
                    task_query=merge_request,
                    history=[],
                )
                if merged and not self._is_raw_routing_json(merged):
                    return merged
                print("[AgentRouter] Supervisor merge returned raw routing JSON, falling back.")
            except Exception as e:
                print(f"[AgentRouter] Supervisor merge failed: {e}. Using fallback.")

        # Direct OpenAI merge fallback
        if self._openai_client:
            try:
                deployment = os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-4o")
                merge_prompt = (
            "You are a response synthesiser for a Sainsbury's retail assistant.\n"
            "Merge the following agent responses into a single, coherent, friendly reply.\n"
            "Be concise. Do not repeat information. Use British English."
        )
                loop = asyncio.get_event_loop()
                def call_merge():
                    return self._openai_client.chat.completions.create(
                        model=deployment,
                        messages=[
                            {"role": "system", "content": merge_prompt},
                            {"role": "user", "content": merge_request}
                        ],
                        max_completion_tokens=500,
                        temperature=0.0,
                    )
                res = await loop.run_in_executor(None, call_merge)
                content = res.choices[0].message.content.strip()
                if content and not self._is_raw_routing_json(content):
                    return content
            except Exception as e:
                print(f"[AgentRouter] Direct OpenAI merge failed: {e}")

        # Local fallback: simple join with separator
        return "\n\n".join(replies)

    async def _generate_suggestions(
        self, message: str, reply: str, intent: str, history: list[dict]
    ) -> list[str]:
        """
        Dynamically generates 3-5 follow-up suggestions based on the last message.
        """
        fallback_map = {
            "order": [
                "Track my order",
                "Can I see my recent orders?",
                "How do I cancel my order?",
                "Contact customer support"
            ],
            "delivery": [
                "Track my delivery",
                "Change delivery slot",
                "Update delivery address",
                "Contact the driver",
                "Cancel delivery"
            ],
            "refund": [
                "Check refund status",
                "How long does a refund take?",
                "Request a replacement",
                "Show refund history",
                "Contact support"
            ],
            "store": [
                "What are the opening hours?",
                "Check product stock levels",
                "Show active promotions",
                "Find nearest store"
            ],
            "general": [
                "What can you help me with?",
                "Show me suggestion chips",
                "How do I track orders?"
            ]
        }
        
        default_suggestions = fallback_map.get(intent, fallback_map["general"])
        
        if not self._openai_client:
            return default_suggestions
            
        try:
            deployment = os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-4o")
            history_snippet = "\n".join(
                f"{t['role'].upper()}: {t['content']}"
                for t in history[-4:]
            )
            
            system_prompt = (
            "You are a helpful Sainsbury's retail assistant.\n"
            "Based on the conversation, suggest 3 short follow-up questions the user might ask next.\n"
            "Return ONLY a JSON array of strings. Example: [\"Where is my order?\", \"Can I return it?\"]"
        )
            user_input = (
                f"CONVERSATION HISTORY:\n{history_snippet}\n\n"
                f"LAST USER MESSAGE: {message}\n\n"
                f"ASSISTANT REPLY:\n{reply}\n\n"
                f"INTENT CATEGORY: {intent}"
            )
            
            loop = asyncio.get_event_loop()
            
            def call_completion():
                return self._openai_client.chat.completions.create(
                    model=deployment,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_input}
                    ],
                    max_completion_tokens=150,
                    temperature=0.0,
                )
                
            resp = await loop.run_in_executor(None, call_completion)
            content = resp.choices[0].message.content.strip()
            
            # Strip markdown JSON fences if present
            clean = re.sub(r"^```(?:json)?\n?", "", content)
            clean = re.sub(r"\n?```$", "", clean)
            suggestions = json.loads(clean)
            
            if isinstance(suggestions, list) and len(suggestions) >= 2:
                # Deduplicate and limit to 3-5 suggestions
                seen = set()
                deduped = []
                for s in suggestions:
                    s_clean = s.strip()
                    if s_clean and s_clean.lower() not in seen:
                        seen.add(s_clean.lower())
                        deduped.append(s_clean)
                if 3 <= len(deduped) <= 5:
                    return deduped
                elif len(deduped) > 5:
                    return deduped[:5]
                elif len(deduped) > 0:
                    for fallback in default_suggestions:
                        if len(deduped) >= 3:
                            break
                        if fallback.lower() not in seen:
                            deduped.append(fallback)
                            seen.add(fallback.lower())
                    return deduped
        except Exception as e:
            print(f"[AgentRouter] Suggestion generation failed: {e}")
            
        return default_suggestions

    _STATIC_SUGGESTIONS: dict[str, list[str]] = {
        "order":    ["View my recent orders", "Check order payment", "Show Nectar points"],
        "delivery": ["Track my delivery", "Change delivery slot", "Update delivery address"],
        "refund":   ["Check refund status", "How long does a refund take?", "Request a replacement"],
        "store":    ["Check product stock", "Show store hours", "Active promotions"],
        "general":  ["Track my order", "Find nearest store", "Check product stock"],
    }

    def _static_suggestions(self, intent: str) -> list[str]:
        return self._STATIC_SUGGESTIONS.get(intent, self._STATIC_SUGGESTIONS["general"])

    # ─────────────────────────────────────────────────────────────────────────
    # Voice-Optimised Direct OpenAI Call (sub-1s path)
    # ─────────────────────────────────────────────────────────────────────────

    async def _call_voice_openai(
        self, message: str, customer_data: dict, history: list[dict]
    ) -> str:
        """
        Direct AzureOpenAI call for voice — bypasses Foundry agents entirely.
        """
        if not self._openai_client:
            return ""

        # ── Build a compact voice-ready customer summary ──────────────────────
        cust    = customer_data.get("customer") or customer_data
        orders  = customer_data.get("orders", [])
        name    = cust.get("name", "there")
        loyalty = cust.get("loyalty_points", 0)
        email   = cust.get("email", "")

        # Summarise most recent order (field names match the DB schema)
        recent_order_summary = "No recent orders found."
        if orders:
            o        = orders[-1]
            delivery = o.get("delivery") or {}
            if isinstance(delivery, str):
                delivery = {}
            refund   = o.get("refund") or {}
            if isinstance(refund, str):
                refund = {}
            items = o.get("items") or []
            items_str = ""
            if isinstance(items, list):
                items_str = ", ".join(
                    f"{it.get('name','item')} x{it.get('qty', it.get('quantity', 1))}"
                    for it in items[:4]
                )
            recent_order_summary = (
                f"Latest order {o.get('order_id','')}: {items_str or 'items unavailable'}. "
                f"Status: {o.get('status','unknown')}. "
                f"Total: £{o.get('total', o.get('total_price', 0)):.2f}. "
                f"Delivery: {delivery.get('method','N/A')}. "
                f"Slot: {delivery.get('slot', 'N/A')}. "
                f"Driver: {delivery.get('driver','N/A')}. "
            )
            if refund.get("reference") or refund.get("refund_id"):
                ref_id  = refund.get("reference") or refund.get("refund_id", "")
                ref_amt = refund.get("amount") or refund.get("refund_amount", 0)
                recent_order_summary += (
                    f"Refund {ref_id}: £{ref_amt:.2f} - {refund.get('status','')}. "
                    f"Reason: {refund.get('reason','')}."
                )

        # All orders summary (last 3)
        all_orders_summary = ""
        for o in orders[-3:]:
            all_orders_summary += (
                f"Order {o.get('order_id','')}: "
                f"status={o.get('status','')}, "
                f"total=£{o.get('total', o.get('total_price', 0)):.2f}. "
            )

        voice_system_prompt = _build_voice_prompt(
            name=name,
            email=email,
            loyalty=loyalty,
            recent_order_summary=recent_order_summary,
            all_orders_summary=all_orders_summary,
        )

        deployment = os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-4o")

        # Build message history (last 3 turns only)
        msgs: list[dict] = [{"role": "system", "content": voice_system_prompt}]
        for t in history[-3:]:
            r = t.get("role", "user")
            c = t.get("content", "").strip()
            if r in ("user", "assistant") and c:
                # Truncate long history entries to save tokens
                msgs.append({"role": r, "content": c[:200]})
        msgs.append({"role": "user", "content": message})

        try:
            if self._async_openai_client:
                t_start = time.perf_counter()
                resp = await self._async_openai_client.chat.completions.create(
                    model=deployment,
                    messages=msgs,
                    max_completion_tokens=60,     # hard cap → forces short answers
                    temperature=0.0,    # deterministic, fastest
                    top_p=1.0,
                    frequency_penalty=0.0,
                    presence_penalty=0.0,
                )
                t_done = time.perf_counter() - t_start
                reply = resp.choices[0].message.content.strip()
                print(f"[AgentRouter][VOICE] Async reply ({resp.usage.completion_tokens} tokens) in {t_done:.3f}s: {reply[:100]}")
                return reply

            # Synchronous fallback with thread pool
            loop = asyncio.get_event_loop()

            def _call():
                t0 = time.perf_counter()
                res = self._openai_client.chat.completions.create(
                    model=deployment,
                    messages=msgs,
                    max_completion_tokens=60,     # hard cap → forces short answers
                    temperature=0.0,    # deterministic, fastest
                    top_p=1.0,
                    frequency_penalty=0.0,
                    presence_penalty=0.0,
                )
                dt = time.perf_counter() - t0
                print(f"[AgentRouter][VOICE] completions call took {dt:.3f}s")
                return res

            t_start = time.perf_counter()
            resp  = await loop.run_in_executor(None, _call)
            t_done = time.perf_counter() - t_start
            reply = resp.choices[0].message.content.strip()
            print(f"[AgentRouter][VOICE] Sync reply ({resp.usage.completion_tokens} tokens) in {t_done:.3f}s: {reply[:100]}")
            return reply

        except Exception as e:
            print(f"[AgentRouter][VOICE] Direct OpenAI call failed: {e}")
            return ""

    # ─────────────────────────────────────────────────────────────────────────
    # Public Handler – Main Orchestration Entry Point
    # ─────────────────────────────────────────────────────────────────────────

    async def handle(self, message: str, history: list[dict], is_voice: bool = False) -> dict[str, Any]:
        """
        Dual-path orchestration.
        """

        # ── Shared: instant greeting/pleasantry short-circuit ─────────────────
        cleaned_msg = re.sub(r'[^\w\s]', '', message).lower().strip()

        if cleaned_msg in ("hello", "hi", "hey", "good morning", "good afternoon",
                           "good evening", "hello there", "hi there"):
            return {
                "reply": "Hello! How can I help you with your Sainsbury's orders, deliveries, refunds, or product stock today? 😊",
                "intent": "store",
                "sources": ["local_greeting"],
                "suggestions": ["Track my order", "Find nearest store", "Check product stock"],
            }

        if cleaned_msg in ("can you hear me", "can you hear me now", "is anyone there",
                           "is anybody there", "anyone there", "anybody there"):
            return {
                "reply": "Yes, I can hear you clearly! How can I help you with your Sainsbury's orders, deliveries, or refunds today? 😊",
                "intent": "store",
                "sources": ["local_greeting"],
                "suggestions": ["Track my order", "Find nearest store", "Check product stock"],
            }

        if cleaned_msg in ("thanks", "thank you", "thank you very much", "cheers", "great thanks"):
            return {
                "reply": "You're very welcome! Let me know if there is anything else I can do for you. 😊",
                "intent": "store",
                "sources": ["local_greeting"],
                "suggestions": ["Track my order", "Find nearest store", "Check product stock"],
            }

        # ── Refresh customer context ──────────────────────────────────────────
        customer_data = self._load_customer_data()
        self.context  = build_context_block(customer_data)

        # ── Strict Guardrail: Check for out-of-context requests ───────────────
        if self._is_out_of_context(message):
            print(f"[AgentRouter] Guardrail triggered for out-of-context message: {message[:80]}")
            if is_voice:
                return {
                    "reply":       VOICE_DECLINE_MESSAGE,
                    "intent":      "general",
                    "sources":     ["guardrail_decline"],
                    "suggestions": self._static_suggestions("general"),
                }
            else:
                return {
                    "reply":       CHAT_DECLINE_MESSAGE,
                    "intent":      "general",
                    "sources":     ["guardrail_decline"],
                    "suggestions": await self._generate_suggestions(message, CHAT_DECLINE_MESSAGE, "general", history),
                }

        # ═════════════════════════════════════════════════════════════════════
        # VOICE FAST PATH — Direct OpenAI call, no Foundry agents
        # ═════════════════════════════════════════════════════════════════════
        if is_voice:
            print(f"[AgentRouter][VOICE] Voice path for: {message[:80]}")

            # Route to correct domain
            agent_type = self._classify_fallback(message)
            print(f"[AgentRouter][VOICE] Classified Domain: {agent_type}")

            reply = await self._call_voice_openai(message, customer_data, history)
            sources = ["voice_direct"]

            if not reply:
                reply = "I'm sorry, could you say that again?"
                sources = ["voice_failed"]

            return {
                "reply":       reply,
                "intent":      agent_type,
                "sources":     sources,
                "suggestions": self._static_suggestions(agent_type),
            }


        # ═════════════════════════════════════════════════════════════════════
        # CHAT FULL PIPELINE — detailed responses with full agent routing
        # ═════════════════════════════════════════════════════════════════════

        # ── 1. Intent classification ──────────────────────────────────────────
        intent = self._classify_intent(message, history, is_voice=False)
        print(f"[AgentRouter] Intent: {intent} | Message: {message[:80]}")

        is_follow_up = intent in ("follow_up", "clarification_confirmation")
        if is_follow_up:
            resolution = await self._resolve_context(message, history)
            print(f"[AgentRouter] Context Resolution: {resolution}")
            if resolution["type"] == "clarification":
                reply = resolution["response"]
                validated = await self._run_validation_layer(message, reply)
                suggestions = await self._generate_suggestions(message, validated, "store", history)
                return {
                    "reply":       validated,
                    "intent":      "store",
                    "sources":     ["context_resolver_clarification"],
                    "suggestions": suggestions,
                }
            else:
                message = resolution["query"]
                print(f"[AgentRouter] Standalone resolved message: {message}")

        # ── 2. Domain classification ──────────────────────────────────────────
        domain = self._classify_domain(message, history, is_voice=False)
        print(f"[AgentRouter] Domain: {domain} | Resolved Message: {message[:80]}")

        # ── 3. General-knowledge questions ────────────────────────────────────
        if domain == "general" or (intent == "new_general" and not is_follow_up):
            general_id = self._agent_ids.get("general")
            if general_id and self._openai_client:
                try:
                    reply = await self._call_foundry_agent(
                        agent_id=general_id,
                        context=self.context,
                        task_query=message,
                        history=history,
                    )
                    if not self._is_raw_routing_json(reply):
                        validated = await self._run_validation_layer(message, reply)
                        suggestions = await self._generate_suggestions(message, validated, "general", history)
                        return {
                            "reply":       validated,
                            "intent":      "general",
                            "sources":     ["general_assistant_agent"],
                            "suggestions": suggestions,
                        }
                except Exception as e:
                    print(f"[AgentRouter] General-Assistant-Agent call failed: {e}")

            decline = (
                "I'm your Sainsbury's retail assistant, here to help with shopping, "
                "products, orders, deliveries, refunds, stores, and offers. "
                "For general knowledge questions I'm afraid I'm not the right tool — "
                "but feel free to ask me anything retail-related! 😊"
            )
            suggestions = await self._generate_suggestions(message, decline, "general", history)
            return {
                "reply":       decline,
                "intent":      "general",
                "sources":     ["polite_decline"],
                "suggestions": suggestions,
            }

        # ── 4. Retail: product-info DB lookup ─────────────────────────────────
        db_result = self._search_db_for_product_question(message)
        if db_result:
            print("[AgentRouter] Answered from product catalog DB directly.")
            validated = await self._run_validation_layer(message, db_result)
            validated = self.append_product_grid_if_mentioned(validated)
            suggestions = await self._generate_suggestions(message, validated, "store", history)
            return {
                "reply":       validated,
                "intent":      "store",
                "sources":     ["product_catalog_db"],
                "suggestions": suggestions,
            }

        # ── 5. Routing: direct keywords or Supervisor decomposition ───────────
        tasks = self._get_direct_routing_tasks(message)
        if tasks:
            print(f"[AgentRouter] Direct keyword routing: {tasks}")
        else:
            tasks = await self._decompose_via_supervisor(message, history)
            print(f"[AgentRouter] Supervisor routing tasks: {tasks}")

        # ── 6. Invoke specialist agents (parallel when multiple tasks) ────────
        async def call_agent(task: dict) -> str:
            agent_type = task.get("agent", "order")
            task_query = task.get("task_query", message)
            agent_id   = self._agent_ids.get(agent_type)

            if agent_id and self._openai_client:
                try:
                    reply = await self._call_foundry_agent(
                        agent_id=agent_id,
                        context=self.context,
                        task_query=task_query,
                        history=history,
                    )
                    if not self._is_raw_routing_json(reply):
                        return reply
                    print(f"[AgentRouter] JSON bleed-through detected for {agent_type}, using OpenAI fallback.")
                except Exception as e:
                    print(f"[AgentRouter] Foundry {agent_type} agent failed: {e}. Falling back.")

            # OpenAI direct fallback
            if self._openai_client:
                try:
                    deployment = os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-4o")
                    msgs = [{"role": "system", "content": self.context}]
                    for t in history[-4:]:
                        r, c = t.get("role", "user"), t.get("content", "").strip()
                        if r in ("user", "assistant") and c:
                            msgs.append({"role": r, "content": c})
                    msgs.append({"role": "user", "content": task_query})
                    tools = self._agent_tools.get(agent_type, [])
                    resp  = self._openai_client.chat.completions.create(
                        model=deployment,
                        messages=msgs,
                        tools=tools if tools else None,
                        tool_choice="auto" if tools else None,
                        max_completion_tokens=800,
                        temperature=0.0,
                    )
                    msg = resp.choices[0].message
                    if msg.tool_calls:
                        msgs.append(msg)
                        for tc in msg.tool_calls:
                            result = self._execute_tool(tc.function.name, json.loads(tc.function.arguments))
                            msgs.append({"role": "tool", "tool_call_id": tc.id,
                                         "name": tc.function.name, "content": result})
                        updated = self._load_customer_data()
                        self.context = build_context_block(updated)
                        msgs[0]["content"] = self.context
                        final = self._openai_client.chat.completions.create(
                            model=deployment, messages=msgs, max_completion_tokens=800, temperature=0.0)
                        return final.choices[0].message.content.strip()
                    return msg.content.strip()
                except Exception as e:
                    print(f"[AgentRouter] OpenAI fallback failed for {agent_type}: {e}")

            return (f"I'm sorry, the {agent_type} specialist is currently unavailable. "
                    "Please try again shortly.")

        # Run all agent tasks in parallel
        replies = await asyncio.gather(*[call_agent(t) for t in tasks])
        sources = [f"{t.get('agent', 'order')}_agent" for t in tasks]

        if not replies:
            replies = ["I'm sorry, I was unable to process your request. Please try again."]

        # ── 7. Merge replies ──────────────────────────────────────────────────
        merged = await self._merge_replies(message, tasks, list(replies))

        # ── 8. Validate, sanitize, append product grid ────────────────────────
        validated = await self._run_validation_layer(message, merged)
        if domain != "general":
            validated = self.append_product_grid_if_mentioned(validated)

        # ── 9. Dynamic suggestions ────────────────────────────────────────────
        primary_intent = tasks[0]["agent"] if tasks else "order"
        suggestions = await self._generate_suggestions(message, validated, primary_intent, history)

        return {
            "reply":       validated,
            "intent":      primary_intent,
            "sources":     sources,
            "suggestions": suggestions,
        }
