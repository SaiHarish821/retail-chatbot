import os
import json
import logging
import asyncio
import base64
from typing import Any

from agents.tools import (
    search_products,
    check_stock,
    get_active_promotions,
    update_customer_address,
    issue_refund
)

logger = logging.getLogger(__name__)


def get_azure_credential():
    """Resolve Azure credential for Voice Live authentication.
    
    Uses ClientSecretCredential for deployed environments (Render/Railway)
    and falls back to AzureCliCredential for local dev (az login).
    """
    from azure.identity import AzureCliCredential, ClientSecretCredential
    tenant_id = os.getenv("AZURE_TENANT_ID", "").strip() or None
    client_id = os.getenv("AZURE_CLIENT_ID", "").strip() or None
    client_secret = os.getenv("AZURE_CLIENT_SECRET", "").strip() or None
    
    if client_id and client_secret and tenant_id:
        logger.info("[VoiceRealtime] Using ClientSecretCredential for authentication")
        return ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret
        )
    else:
        logger.info(f"[VoiceRealtime] Using AzureCliCredential for authentication (tenant_id={tenant_id})")
        return AzureCliCredential(tenant_id=tenant_id) if tenant_id else AzureCliCredential()


def strip_markdown(text: str) -> str:
    """Remove asterisks the model uses for markdown emphasis/bullets, so the
    voice transcript reads as clean plain text (it's spoken, not rendered)."""
    return text.replace("*", "")


async def execute_voice_tool(name: str, arguments: dict, agent_router) -> str:
    """Execute a retail tool invoked by the Voice Live agent.
    
    This keeps local tool execution so the voice assistant can use tools
    that may not be registered directly on the Foundry agent.
    """
    logger.info(f"[VoiceRealtime] Executing tool '{name}' with args: {arguments}")
    try:
        if name == "search_products_tool":
            return search_products(
                agent_router,
                query=arguments.get("query"),
                category=arguments.get("category"),
                dietary_filters=arguments.get("dietary_filters"),
                sort_by=arguments.get("sort_by"),
                is_on_promotion=arguments.get("is_on_promotion")
            )
        elif name == "check_stock_tool":
            return check_stock(
                agent_router,
                product_name=arguments.get("product_name"),
                store_name=arguments.get("store_name")
            )
        elif name == "get_active_promotions_tool":
            return get_active_promotions(agent_router)
        elif name == "update_customer_address_tool":
            return update_customer_address(
                agent_router,
                postcode=arguments.get("postcode"),
                line1=arguments.get("new_address", arguments.get("line1")),
                city="London"
            )
        elif name == "issue_refund_tool":
            return issue_refund(
                agent_router,
                order_id=arguments.get("order_id"),
                reason=arguments.get("reason")
            )
        elif name == "transfer_to_human_agent_tool":
            logger.info(f"[VoiceRealtime] Initiating handoff to live agent. Reason: {arguments.get('reason')}")
            return "I am now transferring you to a live customer support representative. Please hold."
        else:
            return f"Tool '{name}' is not registered."
    except Exception as e:
        logger.error(f"[VoiceRealtime] Error executing tool '{name}': {e}")
        return f"Error executing tool '{name}': {str(e)}"

# JSON tool definitions compliant with OpenAI Realtime API specification
REALTIME_TOOLS = [
    {
        "type": "function",
        "name": "search_products_tool",
        "description": "Searches and filters the product catalog using criteria like name, category, dietary tags, promotions, and custom sorting.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term for products"},
                "category": {"type": "string", "description": "Filter by product category (e.g., Dairy, Bakery)"},
                "dietary_filters": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by dietary tags (e.g., Gluten-Free, Vegan, Organic)"
                },
                "sort_by": {"type": "string", "description": "Sort ordering (e.g., price_low_to_high, price_high_to_low)"},
                "is_on_promotion": {"type": "boolean", "description": "Filter for products on discount or promotions"}
            }
        }
    },
    {
        "type": "function",
        "name": "check_stock_tool",
        "description": "Checks real-time inventory stock levels of a product at a specific Sainsbury's store branch.",
        "parameters": {
            "type": "object",
            "properties": {
                "product_name": {"type": "string", "description": "Name of the product"},
                "store_name": {"type": "string", "description": "Name of the store branch"}
            },
            "required": ["product_name"]
        }
    },
    {
        "type": "function",
        "name": "get_active_promotions_tool",
        "description": "Retrieves all active customer promotions, member discounts, and coupons.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "type": "function",
        "name": "update_customer_address_tool",
        "description": "Updates the customer's shipping postcode and delivery address in the database.",
        "parameters": {
            "type": "object",
            "properties": {
                "postcode": {"type": "string", "description": "Postcode of the new address"},
                "new_address": {"type": "string", "description": "Line 1 of the new address"}
            },
            "required": ["postcode", "new_address"]
        }
    },
    {
        "type": "function",
        "name": "issue_refund_tool",
        "description": "Issues a refund for a damaged, spoiled, or missing item in an order.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The ID of the order (e.g. ORD-98741)"},
                "reason": {"type": "string", "description": "Reason for requesting the refund (e.g. damaged)"}
            },
            "required": ["order_id", "reason"]
        }
    },
    {
        "type": "function",
        "name": "transfer_to_human_agent_tool",
        "description": "Transfers the customer's call to a live human agent customer support representative.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "The reason why the customer wants to talk to a human agent"}
            },
            "required": ["reason"]
        }
    }
]
