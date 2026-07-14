"""
Retail AI Assistant – Main Orchestration and Routing Layer (LangGraph Orchestrated with Specialist Agents)
"""

import os
import json
import re
import asyncio
import logging
from typing import Any, Optional, List, Dict

from azure.identity import AzureCliCredential
from azure.ai.projects import AIProjectClient
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

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

class AgentRouter:
    """
    Orchestrates Azure AI Foundry models and agents using LangGraph.
    No LLM prompts or instructions are hardcoded in the codebase –
    all safety configurations and instructions are managed inside Azure AI Foundry.
    """

    _ACKNOWLEDGEMENTS: frozenset = frozenset([
        "yes", "yeah", "yep", "yup", "sure", "okay", "ok", "alright", "sounds good",
        "go ahead", "continue", "next", "show me", "tell me more", "more",
        "thats fine", "that's fine", "do it", "proceed", "exactly", "correct", "right",
        "this one", "that one", "first one", "second one"
    ])

    # Bind validation and sanitization functions for compatibility
    async def _run_validation_layer(self, query: str, reply: str) -> str:
        return await run_validation_layer(query, reply)

    def _is_raw_routing_json(self, text: str) -> bool:
        return is_raw_routing_json(text)

    # Bind tool functions
    check_stock = check_stock
    search_products = search_products
    get_active_promotions = get_active_promotions
    update_customer_address = update_customer_address
    issue_refund = issue_refund
    append_product_grid_if_mentioned = append_product_grid_if_mentioned

    def __init__(self, customer_data: dict):
        self.customer_data = customer_data
        self.context = build_context_block(customer_data)
        self._openai_client = None
        self._project_client = None
        self._agent_instructions = {}
        self._agent_ids = {}
        
        # Token and LLM instance caching fields
        self._llm_instance = None
        self._token_expires_on = 0
        self._cached_token = None
        
        self._init_clients()
        self._fetch_instructions()

    def _get_credential(self):
        from azure.identity import AzureCliCredential, ClientSecretCredential
        tenant_id = os.getenv("AZURE_TENANT_ID", "").strip() or None
        client_id = os.getenv("AZURE_CLIENT_ID", "").strip() or None
        client_secret = os.getenv("AZURE_CLIENT_SECRET", "").strip() or None
        
        if client_id and client_secret and tenant_id:
            logger.info("[AgentRouter] Using ClientSecretCredential for authentication")
            return ClientSecretCredential(
                tenant_id=tenant_id,
                client_id=client_id,
                client_secret=client_secret
            )
        else:
            logger.info(f"[AgentRouter] Using AzureCliCredential for authentication (tenant_id={tenant_id})")
            return AzureCliCredential(tenant_id=tenant_id) if tenant_id else AzureCliCredential()

    def _init_clients(self) -> None:
        project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
        api_key          = os.getenv("AZURE_AI_FOUNDRY_API_KEY", "").strip()
        openai_endpoint  = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()

        if project_endpoint:
            try:
                credential = self._get_credential()
                self._project_client = AIProjectClient(
                    endpoint=project_endpoint,
                    credential=credential,
                )
                self._openai_client = self._project_client.get_openai_client()
                logger.info("[AgentRouter] AIProjectClient and OpenAI client initialised successfully.")
            except Exception as e:
                logger.error(f"[AgentRouter] Initialization failed: {e}")

        # Fallback to direct AzureOpenAI client if key and endpoint are provided and project client failed
        if not self._openai_client and api_key and openai_endpoint:
            try:
                from openai import AzureOpenAI
                self._openai_client = AzureOpenAI(
                    azure_endpoint=openai_endpoint,
                    api_key=api_key,
                    api_version="2024-06-01"
                )
                logger.info("[AgentRouter] Direct AzureOpenAI client initialized using API key fallback.")
            except Exception as e:
                logger.error(f"[AgentRouter] Direct AzureOpenAI client initialization failed: {e}")

    def _fetch_instructions(self) -> None:
        if not self._project_client:
            return
        try:
            logger.info("[AgentRouter] Fetching agent instructions dynamically from Portal...")
            agents = list(self._project_client.agents.list())
            available = {a.name: a for a in agents}
            
            roles_map = {
                "order":    os.getenv("AZURE_AGENT_ORDER_NAME",      "Order-Agent"),
                "delivery": os.getenv("AZURE_AGENT_DELIVERY_NAME",   "Delivery-Agent"),
                "refund":   os.getenv("AZURE_AGENT_REFUND_NAME",     "Refund-Agent"),
                "store":    os.getenv("AZURE_AGENT_STORE_NAME",      "Store-Agent"),
                "general":  os.getenv("AZURE_AGENT_GENERAL_NAME",    "General-Assistant-Agent"),
                "intent_classifier": os.getenv("AZURE_AGENT_INTENT_NAME", "Intent-Classifier-Agent"),
                "context_resolver":  os.getenv("AZURE_AGENT_CONTEXT_NAME",  "Context-Resolver-Agent"),
                "voice_assistant":   os.getenv("AZURE_AGENT_VOICE_NAME",   "Voice-Assistant-Agent"),
            }
            
            for role, agent_name in roles_map.items():
                agent = available.get(agent_name)
                if agent:
                    latest = agent.versions.get("latest", {}) if hasattr(agent, "versions") else {}
                    guid = latest.get("agent_guid") if hasattr(latest, "get") else None
                    resolved_id = guid or agent.id
                    
                    self._agent_ids[role] = resolved_id
                    instructions = latest.get("definition", {}).get("instructions", "")
                    if instructions:
                        self._agent_instructions[role] = instructions
                        logger.info(f"[AgentRouter] Loaded instructions for '{role}' agent (Name: {agent.name}, Resolved ID/GUID: {resolved_id}).")
                        continue
                
                # Default fallback instructions
                if role == "intent_classifier":
                    self._agent_instructions[role] = (
                        "You are an intent classifier for a Sainsbury's retail chatbot.\n"
                        "Analyze the user's message and the conversation history.\n"
                        "Classify the intent into exactly one of the following labels:\n"
                        "- 'follow_up': If the user is replying to a previous specialist agent question or continuing a topic.\n"
                        "- 'clarification_confirmation': If the user is saying a brief acknowledgement/confirmation (like 'yes', 'no', 'sure', 'okay') in response to a choice.\n"
                        "- 'new_retail': If the user is asking a new question specifically about Sainsbury's retail processes.\n"
                        "- 'new_general': If the user is asking about anything else (jokes, general queries, coding, math, recipes, non-retail pleasantries, chit-chat).\n\n"
                        "Output ONLY the raw label name ('follow_up', 'clarification_confirmation', 'new_retail', 'new_general') and nothing else."
                    )
                elif role == "context_resolver":
                    self._agent_instructions[role] = (
                        "You are a conversation context resolver for a Sainsbury's retail chatbot.\n"
                        "Analyze the conversation history and the user's latest ambiguous input (such as 'yes', 'no', 'sure', 'do it', 'okay') and resolve what the user is referring to.\n\n"
                        "If the previous assistant message presented a binary choice or a list of options (e.g. 'Would you like delivery or Click & Collect?' or 'Would you like directions or help online?'):\n"
                        "- If the user's message is ambiguous ('yes', 'sure', 'okay', 'both') and does not select one, you must ask for clarification.\n"
                        "  Output a JSON object:\n"
                        "  {\n"
                        "    \"type\": \"clarification\",\n"
                        "    \"response\": \"Prompt the user to clarify between the options.\"\n"
                        "  }\n\n"
                        "If the previous assistant message offered a single option (e.g. 'Would you like to check the price?'):\n"
                        "- If the user says 'yes', 'sure', or similar, resolve this to a concrete query.\n"
                        "  Output a JSON object:\n"
                        "  {\n"
                        "    \"type\": \"resolved_query\",\n"
                        "    \"query\": \"The resolved concrete query (e.g. 'Check the current price of Salmon Fillets 400g at the store.')\"\n"
                        "  }\n\n"
                        "Otherwise:\n"
                        "- If it cannot be resolved or is a new query, resolve it to the message.\n"
                        "  Output a JSON object:\n"
                        "  {\n"
                        "    \"type\": \"resolved_query\",\n"
                        "    \"query\": \"user message\"\n"
                        "  }\n\n"
                        "Output ONLY valid raw JSON."
                    )
                else:
                    self._agent_instructions[role] = (
                        f"You are the specialist {role} support agent for Sainsbury's.\n"
                        f"Help customers with issues regarding {role} processes."
                    )
                logger.warning(f"[AgentRouter] Instructions for '{agent_name}' not found. Using fallback.")
        except Exception as e:
            logger.error(f"[AgentRouter] Failed to fetch agent instructions: {e}")

    def get_agent_id(self, role: str) -> str:
        """Returns the dynamically resolved agent UUID/ID for a role."""
        return self._agent_ids.get(role, "")

    def _load_customer_data(self) -> dict:
        from database import load_db_customer_data
        return load_db_customer_data()

    def _save_customer_data(self, data: dict) -> None:
        from database import save_db_customer_data
        save_db_customer_data(data)

    def _load_inventory_data(self) -> dict:
        from database import load_db_inventory_data
        return load_db_inventory_data()

    def _classify_intent(self, message: str, history: list[dict], is_voice: bool = False) -> str:
        """Synchronous intent classifier calling Azure completions for test compatibility."""
        cleaned = message.lower().strip().rstrip('?.!')
        if cleaned in ("hello", "hi", "hey", "thanks", "thank you", "cheers"):
            return "new_retail"

        if not self._openai_client:
            if cleaned in self._ACKNOWLEDGEMENTS:
                return "clarification_confirmation"
            return "new_retail"

        instructions = self._agent_instructions.get("intent_classifier", "")
        if not instructions:
            if cleaned in self._ACKNOWLEDGEMENTS:
                return "clarification_confirmation"
            return "new_retail"

        history_snippet = "\n".join(
            f"{t['role'].upper()}: {t['content']}"
            for t in history[-5:]
        )
        user_input = f"CONVERSATION HISTORY:\n{history_snippet}\n\nUSER MESSAGE: {message}"

        try:
            deployment = os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-5.1")
            kwargs = {
                "model": deployment,
                "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": user_input}
                ],
                "max_completion_tokens": 10,
            }
            if "mini" not in deployment.lower() and "o1" not in deployment.lower():
                kwargs["temperature"] = 0.0
            res = self._openai_client.chat.completions.create(**kwargs)
            label = res.choices[0].message.content.strip().lower()
            label = re.sub(r'[^\w\-]', '', label)
            if label in ("follow_up", "clarification_confirmation", "new_retail", "new_general"):
                return label
        except Exception as e:
            logger.error(f"[AgentRouter] Sync intent classification failed: {e}")

        if cleaned in self._ACKNOWLEDGEMENTS:
            return "clarification_confirmation"
        return "new_retail"

    def _get_llm(self) -> ChatOpenAI:
        """Helper to retrieve or initialize the cached LangChain ChatOpenAI instance using Entra tokens or API Key fallback."""
        import time
        now = time.time()

        # Derive OpenAI inference endpoint if not explicitly provided
        project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
        openai_endpoint  = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
        if not openai_endpoint and project_endpoint:
            openai_endpoint = f"{project_endpoint.rstrip('/')}/inference/v1"

        api_key = os.getenv("AZURE_AI_FOUNDRY_API_KEY", "").strip()

        # Direct key-based authentication fallback
        if api_key and openai_endpoint:
            if not self._llm_instance:
                logger.info("[AgentRouter] Initializing ChatOpenAI directly using API key and endpoint fallback...")
                llm_kwargs = {
                    "openai_api_base": openai_endpoint,
                    "openai_api_key": api_key,
                    "model": os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-5.1"),
                }
                if "mini" not in llm_kwargs["model"].lower() and "o1" not in llm_kwargs["model"].lower():
                    llm_kwargs["temperature"] = 0.0
                self._llm_instance = ChatOpenAI(**llm_kwargs)
            return self._llm_instance

        # Token-based authentication
        if not self._llm_instance or not self._cached_token or self._token_expires_on - now < 300:
            logger.info("[AgentRouter] Re-authenticating and refreshing Entra ID token...")
            cred = self._get_credential()
            token_obj = cred.get_token("https://ai.azure.com/.default")
            self._cached_token = token_obj.token
            self._token_expires_on = token_obj.expires_on
            
            llm_kwargs = {
                "openai_api_base": str(self._openai_client.base_url) if self._openai_client else openai_endpoint,
                "openai_api_key": self._cached_token,
                "model": os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-5.1"),
            }
            if "mini" not in llm_kwargs["model"].lower() and "o1" not in llm_kwargs["model"].lower():
                llm_kwargs["temperature"] = 0.0
            self._llm_instance = ChatOpenAI(**llm_kwargs)
            logger.info(f"[AgentRouter] Refreshed LangChain LLM connection token (expires in {int(self._token_expires_on - now)}s).")
            
        return self._llm_instance

    async def _resolve_context(self, message: str, history: list[dict]) -> dict[str, Any]:
        """Resolves conversation context by delegating to intent service helper."""
        from .intent import resolve_context
        llm = self._get_llm()
        return await resolve_context(
            message,
            history,
            llm,
            self._agent_instructions.get("context_resolver", "")
        )

    async def handle(self, message: str, history: list[dict], is_voice: bool = False, stream_queue = None) -> dict[str, Any]:
        """
        Processes retail queries through LangGraph orchestration.
        """
        # Reload latest data asynchronously
        customer_data = await asyncio.to_thread(self._load_customer_data)
        context_block = await asyncio.to_thread(build_context_block, customer_data)

        # Setup LangChain LLM connection with token caching to bypass 1.8s CLI lookups
        llm = self._get_llm()

        initial_state = {
            "messages": [],
            "message_text": message,
            "history": history,
            "customer_data": customer_data,
            "context_block": context_block,
            "is_voice": is_voice,
            "intent": "",
            "specialist_role": "order",
            "reply": "",
            "sources": [],
            "suggestions": [],
            "agent_instructions": self._agent_instructions,
            "error": None
        }

        # Invoke compiled LangGraph asynchronously
        from .graph import compiled_graph
        config = {
            "configurable": {
                "openai_client": self._openai_client,
                "llm": llm,
                "router_instance": self,
                "stream_queue": stream_queue
            }
        }

        result_state = await compiled_graph.ainvoke(initial_state, config=config)

        # Map specialist_role or intent back to FastAPI expected schema
        final_intent = result_state.get("specialist_role") or result_state.get("intent") or "order"
        
        return {
            "reply":       result_state["reply"],
            "intent":      final_intent,
            "sources":     result_state.get("sources", []),
            "suggestions": result_state.get("suggestions", ["Track my order", "Find nearest store", "Check product stock"]),
        }
