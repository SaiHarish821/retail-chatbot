"""
Retail AI Assistant – Lightweight A2A Orchestration Layer

Azure AI Foundry is the SINGLE SOURCE OF TRUTH for all agent prompts,
instructions, tools, policies, and behavioral rules.

This module ONLY:
  - Resolves Azure AI Foundry agent IDs by name at startup
  - Maintains conversation context from retail_chatbot.db
  - Classifies requests as retail-domain or general-knowledge
  - Queries retail_chatbot.db for product-info questions before routing
  - Invokes Foundry agents via AgentsClient (thread → message → run → poll)
  - Executes tool calls (search_products, check_stock, etc.) locally
  - Aggregates multi-agent responses
  - Sanitizes output formatting

DO NOT add LLM system prompts, agent instructions, routing rules,
or policy text here. Configure those in Azure AI Foundry.
"""

import os
import json
import re
import math
import asyncio
import time
from typing import Any, Optional

from openai import AzureOpenAI
from azure.ai.agents import AgentsClient
from azure.identity import AzureCliCredential

# ─────────────────────────────────────────────────────────────────────────────
# 1. Database Helper Utilities
# ─────────────────────────────────────────────────────────────────────────────

def geocode_postcode(postcode: str) -> tuple[Optional[float], Optional[float]]:
    if not postcode:
        return None, None
    postcode = postcode.upper().strip().replace(" ", "")
    prefixes = {
        "SW1A1AA": (51.5014, -0.1419),
        "SW1A2AA": (51.5014, -0.1419),
        "SW1A":    (51.5014, -0.1419),
        "SW1":     (51.5014, -0.1419),
        "N10PL":   (51.5362, -0.1072),
        "N1":      (51.5362, -0.1072),
        "NW18QR":  (51.5392, -0.1426),
        "NW1":     (51.5392, -0.1426),
        "E151XQ":  (51.5416,  0.0024),
        "E15":     (51.5416,  0.0024),
        "WC2B6XF": (51.5146, -0.1197),
        "WC2B":    (51.5146, -0.1197),
        "WC2":     (51.5146, -0.1197),
    }
    if postcode in prefixes:
        return prefixes[postcode]
    for prefix, coords in prefixes.items():
        if postcode.startswith(prefix):
            return coords
    return 51.5074, -0.1278


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def build_context_block(customer_data: dict) -> str:
    """Serialise customer + order data into a compact context string.

    This block is injected as a user message into each Foundry agent thread
    so that Foundry's system prompt is never overridden.
    """
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

        delivery_info = ""
        if o.get("delivery"):
            d = o["delivery"]
            delivery_info = (
                f' | Delivery: {d.get("method")} status={o["status"]}'
                f' slot={d.get("slot")} driver={d.get("driver")}'
                f' stop={d.get("current_stop")}/{d.get("total_stops")}'
                f' eta={d.get("eta")} url={d.get("live_tracking_url")}'
            )

        orders_summary.append(
            f'  {o["order_id"]} [{o["status"]}] '
            f'GBP{o["total"]:.2f} - {item_names}{refund_info}{delivery_info}'
        )

    first_name = customer["name"].split()[0]

    store_context = "\n\n=== STORE LOCATIONS & DETAILS ===\n"
    try:
        from database import load_db_inventory_data
        inv_data = load_db_inventory_data()
        stores = inv_data.get("metadata", {}).get("stores", {})
        for idx, (sid, sinfo) in enumerate(stores.items(), 1):
            hours = sinfo.get("opening_hours", {})
            hours_str = (
                ", ".join(f"{k}: {v}" for k, v in hours.items())
                if isinstance(hours, dict) else str(hours)
            )
            store_context += (
                f"{idx}. {sinfo['name']} (ID: {sid})\n"
                f"   Address: {sinfo['address']}\n"
                f"   Phone: {sinfo['phone']}\n"
                f"   Hours: {hours_str}\n"
                f"   Type: {sinfo.get('type', 'N/A')}\n"
                f"   Coordinates: Lat {sinfo.get('lat', 'N/A')}, Lng {sinfo.get('lng', 'N/A')}\n\n"
            )
    except Exception:
        store_context += "Store information is currently unavailable.\n"

    return (
        "=== CUSTOMER ORDER CONTEXT ===\n"
        f"Customer: {customer['name']} (ID: {customer['id']})\n"
        f"Loyalty: {customer['loyalty_tier']} - {customer['loyalty_points']} Nectar points\n"
        f"Address: {customer['default_address']['line1']}, "
        f"{customer['default_address']['city']}, {customer['default_address']['postcode']}\n"
        "\nORDERS:\n"
        + "\n".join(orders_summary)
        + store_context
        + f"\nAddress the customer as {first_name}.\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Agent Router – Lightweight Orchestration Layer
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

    def __init__(self, customer_data: dict):
        self.customer_data = customer_data
        self.context = build_context_block(customer_data)
        self._openai_client: Optional[AzureOpenAI] = None
        self._agents_client: Optional[AgentsClient] = None
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
        api_key          = os.getenv("AZURE_AI_FOUNDRY_API_KEY",          "").strip()
        openai_endpoint  = os.getenv("AZURE_OPENAI_ENDPOINT",             "").strip()
        project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
        tenant_id        = os.getenv("AZURE_TENANT_ID", "").strip() or None

        # ── Azure AI Agents client (primary) ─────────────────────────────────
        if project_endpoint:
            try:
                credential = AzureCliCredential(tenant_id=tenant_id)
                self._agents_client = AgentsClient(
                    endpoint=project_endpoint,
                    credential=credential,
                )
                print("[AgentRouter] AgentsClient initialised via AzureCliCredential.")
            except Exception as e:
                print(f"[AgentRouter] AgentsClient init failed: {e}")

        # ── AzureOpenAI client (fallback for classification/merge) ───────────
        if project_endpoint and not self._openai_client:
            try:
                from azure.ai.projects import AIProjectClient
                credential = AzureCliCredential(tenant_id=tenant_id)
                project_client = AIProjectClient(
                    endpoint=project_endpoint, credential=credential
                )
                self._openai_client = project_client.get_openai_client()
                print("[AgentRouter] OpenAI client initialised via AIProjectClient.")
            except Exception as e:
                print(f"[AgentRouter] AIProjectClient OpenAI init failed: {e}")

        if not self._openai_client and api_key and openai_endpoint:
            base = openai_endpoint.rstrip("/")
            if base.endswith("/v1"):
                base = base[:-3]
            self._openai_client = AzureOpenAI(
                api_key=api_key,
                azure_endpoint=base,
                api_version="2024-10-21",
            )
            print("[AgentRouter] AzureOpenAI client initialised via API key (fallback).")

    def _resolve_agent_ids(self) -> None:
        """Map Foundry agent names (from .env) to their runtime asst_* IDs."""
        if not self._agents_client:
            print("[AgentRouter] No AgentsClient – agent ID resolution skipped.")
            return

        name_map = {
            "supervisor": os.getenv("AZURE_AGENT_SUPERVISOR_NAME", "Supervisor-Agent"),
            "order":      os.getenv("AZURE_AGENT_ORDER_NAME",      "Order-Agent"),
            "delivery":   os.getenv("AZURE_AGENT_DELIVERY_NAME",   "Delivery-Agent"),
            "refund":     os.getenv("AZURE_AGENT_REFUND_NAME",     "Refund-Agent"),
            "store":      os.getenv("AZURE_AGENT_STORE_NAME",      "Store-Agent"),
            "general":    os.getenv("AZURE_AGENT_GENERAL_NAME",    "General-Assistant-Agent"),
        }

        try:
            agents = self._agents_client.list_agents()
            available = {a.name: a.id for a in agents}
            print(f"[AgentRouter] Foundry agents available: {list(available.keys())}")

            for role, agent_name in name_map.items():
                if agent_name in available:
                    self._agent_ids[role] = available[agent_name]
                    print(f"[AgentRouter]   {role}: '{agent_name}' → {available[agent_name]}")
                else:
                    print(f"[AgentRouter]   {role}: '{agent_name}' NOT FOUND in Foundry.")
        except Exception as e:
            print(f"[AgentRouter] Error resolving agent IDs: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Database Helpers
    # ─────────────────────────────────────────────────────────────────────────

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
    # Tool Implementations (local DB / business logic)
    # ─────────────────────────────────────────────────────────────────────────

    def check_stock(self, product_name: str, store_name: str = None) -> str:
        try:
            cust_data = self._load_customer_data()
            postcode  = cust_data.get("customer", {}).get("default_address", {}).get("postcode", "")
            cust_lat, cust_lng = geocode_postcode(postcode)
        except Exception:
            cust_lat, cust_lng = None, None

        try:
            data = self._load_inventory_data()
        except Exception as e:
            return f"Error loading inventory database: {e}"

        products    = data.get("inventory", [])
        query       = product_name.lower().strip()
        query_words = query.split()
        matched     = []

        for p in products:
            name_lower   = p["name"].lower()
            cat_lower    = p["category"].lower()
            subcat_lower = p.get("subcategory", "").lower()
            brand_lower  = p.get("brand", "").lower()
            tags         = [t.lower() for t in p.get("tags", [])]
            if (
                query in name_lower
                or query in cat_lower
                or query in subcat_lower
                or all(
                    w in name_lower or w in cat_lower or w in subcat_lower
                    or w in brand_lower or any(w in t for t in tags)
                    for w in query_words
                )
            ):
                matched.append(p)

        if not matched:
            return f"Product '{product_name}' was not found in our inventory."

        results = []
        for p in matched:
            lines = [
                f"Product: {p['name']}",
                f"Price: £{p['price']:.2f}",
                f"Category: {p['category']}",
                f"Aisle: {p.get('aisle', 'N/A')}",
            ]
            store_stock_list = []
            for sid, sinfo in p.get("stock", {}).items():
                qty       = sinfo.get("quantity", 0)
                store_lat = sinfo.get("lat")
                store_lng = sinfo.get("lng")
                sname     = sinfo.get("store_name", sid)
                address   = sinfo.get("address", "")
                hours     = sinfo.get("opening_hours", {})
                stype     = sinfo.get("store_type", "Superstore")
                dist      = None
                if cust_lat is not None and store_lat is not None:
                    dist = haversine_distance(cust_lat, cust_lng, store_lat, store_lng)
                store_stock_list.append({
                    "store_id": sid, "store_name": sname, "quantity": qty,
                    "address": address, "hours": hours, "distance": dist, "type": stype,
                })

            if store_name:
                s_q = store_name.lower().strip()
                store_stock_list = [
                    s for s in store_stock_list
                    if s_q in s["store_name"].lower()
                    or s_q in s["store_id"].lower()
                    or s_q in s["address"].lower()
                ]

            store_stock_list.sort(
                key=lambda x: x["distance"] if x["distance"] is not None else float("inf")
            )

            if not store_stock_list:
                lines.append(
                    f"Stock: Store '{store_name}' not found or has no stock information."
                    if store_name else "Stock: No store stock information available."
                )
            else:
                stock_lines = []
                for s in store_stock_list:
                    dist_str = f"{s['distance']:.2f} miles" if s["distance"] is not None else "N/A"
                    if s["quantity"] == 0:
                        status = "Out of Stock"
                    elif s["quantity"] <= 8:
                        status = "Limited Availability"
                    else:
                        status = "In Stock"
                    hours_str = (
                        ", ".join(f"{k}: {v}" for k, v in s["hours"].items())
                        if isinstance(s["hours"], dict) else str(s["hours"])
                    )
                    stock_lines.append(
                        f"Store: {s['store_name']}\n"
                        f"Distance: {dist_str}\n"
                        f"Hours: {hours_str}\n"
                        f"Facilities: {s['type']}\n"
                        f"Availability: {status}"
                    )
                lines.append("Stock:\n" + "\n\n".join(stock_lines))

            results.append("\n".join(lines))

        return "\n\n".join(results)

    def search_products(
        self,
        query: str = None,
        category: str = None,
        dietary_filters: list = None,
        sort_by: str = None,
        best_seller: bool = None,
        store_recommended: bool = None,
        is_on_promotion: bool = None,
        store_name: str = None,
        limit: int = None,
    ) -> str:
        try:
            data = self._load_inventory_data()
        except Exception as e:
            return f"Error loading inventory database: {e}"

        products = data.get("inventory", [])

        synonyms = {
            "milkk": "milk", "milks": "milk",
            "tomoto": "tomato", "tomotos": "tomato", "tomatoes": "tomato",
            "choclate": "chocolate", "choclates": "chocolate", "chocolates": "chocolate",
            "soda": "drinks", "pop": "drinks", "sparkling": "water",
            "sourdough": "sourdough", "bread": "bread", "breads": "bread",
            "egg": "eggs", "eggs": "eggs", "egs": "eggs",
            "chicken": "chicken", "salmon": "salmon", "fish": "fish",
            "cheese": "cheese", "spinach": "spinach",
            "yoghurt": "yoghurt", "yogurt": "yoghurt",
            "butter": "butter", "pasta": "pasta", "fusilli": "pasta",
            "porcidge": "porridge", "porcige": "porridge", "poridge": "porridge",
        }

        def compute_match_score(p: dict, q_str: str) -> float:
            if not q_str:
                return 1.0
            score    = 0.0
            q_clean  = q_str.lower().strip()
            p_name   = p["name"].lower()
            p_desc   = p["description"].lower()
            p_brand  = p.get("brand", "").lower()
            p_cat    = p["category"].lower()
            p_subcat = p.get("subcategory", "").lower()
            p_tags   = [t.lower() for t in p.get("tags", [])]
            words    = q_clean.split()
            resolved = [synonyms.get(w, w) for w in words]
            resolved_q = " ".join(resolved)
            if resolved_q == p_name:
                score += 150
            elif resolved_q in p_name:
                score += 100
            for w in resolved:
                if w in p_name:
                    score += 40
                elif w in p_desc:
                    score += 10
                elif w in p_cat or w in p_subcat:
                    score += 30
                elif any(w in t for t in p_tags):
                    score += 20
            return score

        matched = []
        if query:
            for p in products:
                score = compute_match_score(p, query)
                if score > 0:
                    matched.append((p, score))
        else:
            matched = [(p, 1.0) for p in products]

        if category:
            cat_clean = category.lower().strip()
            matched = [
                (p, s) for p, s in matched
                if cat_clean in p["category"].lower()
                or cat_clean in p.get("subcategory", "").lower()
            ]

        if dietary_filters:
            filter_map = {
                "organic": "organic", "vegan": "vegan",
                "gluten_free": "gluten_free", "sugar_free": "sugar_free",
                "high_protein": "high_protein", "lactose_free": "lactose_free",
                "healthy_choice": "healthy_choice",
            }
            for df in dietary_filters:
                key = filter_map.get(df.lower().strip())
                if key:
                    matched = [(p, s) for p, s in matched if p.get(key)]

        if best_seller is not None:
            matched = [(p, s) for p, s in matched if p.get("best_seller") == best_seller]
        if store_recommended is not None:
            matched = [(p, s) for p, s in matched if p.get("store_recommended") == store_recommended]
        if is_on_promotion is not None:
            matched = [
                (p, s) for p, s in matched
                if (p.get("discount", {}).get("is_on_sale", False)) == is_on_promotion
            ]

        if store_name:
            s_q = store_name.lower().strip()
            matched = [
                (p, s) for p, s in matched
                if any(
                    (s_q in sinfo.get("store_name", sid).lower()
                     or s_q in sid.lower()
                     or s_q in sinfo.get("address", "").lower())
                    and sinfo.get("quantity", 0) > 0
                    for sid, sinfo in p.get("stock", {}).items()
                )
            ]

        def rec_key(p: dict):
            total_stock = sum(sinfo.get("quantity", 0) for sinfo in p.get("stock", {}).values())
            return (
                1 if total_stock > 0 else 0,
                p.get("popularity_score", 0),
                1 if p.get("best_seller") else 0,
                1 if p.get("store_recommended") else 0,
                p.get("customer_rating", 0.0),
                p.get("review_count", 0),
                1 if (p.get("discount", {}).get("is_on_sale") or p.get("is_on_promotion")) else 0,
            )

        if sort_by == "price_asc":
            matched.sort(key=lambda x: (x[0]["price"], -x[0].get("popularity_score", 0)))
        elif sort_by == "price_desc":
            matched.sort(key=lambda x: (-x[0]["price"], -x[0].get("popularity_score", 0)))
        elif sort_by == "rating":
            matched.sort(key=lambda x: (-x[0].get("customer_rating", 0.0), -x[0].get("popularity_score", 0)))
        elif sort_by == "popularity":
            matched.sort(key=lambda x: (-x[0].get("popularity_score", 0), -x[0].get("customer_rating", 0.0)))
        else:
            matched.sort(key=lambda x: rec_key(x[0]), reverse=True)

        if limit is None:
            m = re.search(r"\b(?:top|best|first|exactly|get|show)\s+(\d+)\b", (query or "").lower())
            limit = int(m.group(1)) if m else 5

        if not matched:
            parts = ([df.replace("_", " ") for df in dietary_filters] if dietary_filters else [])
            if query:
                parts.append(query)
            elif category:
                parts.append(category)
            desc = " ".join(parts) if parts else "matching products"
            return f"I couldn't find any products marked as {desc} in the current inventory."

        prefix = (
            f"We currently have only {len(matched)} products that match your request.\n\n"
            if len(matched) < limit else ""
        )

        def rating_to_stars(rating: float) -> str:
            return "⭐" * min(max(int(round(rating)), 1), 5)

        def generate_explanation(p: dict) -> str:
            factors = []
            if p.get("best_seller"):
                factors.append("one of our best-selling items")
            if p.get("customer_rating", 0.0) >= 4.6:
                factors.append(f"rated {p['customer_rating']} stars by customers")
            if p.get("discount", {}).get("is_on_sale"):
                factors.append(f"currently {p['discount']['offer_text']}")
            if p.get("store_recommended"):
                factors.append("highly recommended by our store managers")
            if p.get("healthy_choice"):
                factors.append("a nutritious, healthy choice")
            if p.get("organic"):
                factors.append("certified organic")
            if not factors:
                brand_name = p.get('brand', "Sainsbury's")
                return f"A high-quality product from {brand_name}."
            if len(factors) == 1:
                reason = factors[0]
            elif len(factors) == 2:
                reason = f"{factors[0]} and {factors[1]}"
            else:
                reason = ", ".join(factors[:-1]) + f", and {factors[-1]}"
            return f"Excellent customer ratings and {reason}."

        lines = []
        for p, _ in matched[:limit]:
            disc      = p.get("discount", {})
            offer_str = disc.get("offer_text", "") if disc.get("is_on_sale") else p.get("promotion_detail", "")
            total_qty = sum(sinfo.get("quantity", 0) for sinfo in p.get("stock", {}).values())
            avail     = ("Out of Stock" if total_qty == 0
                         else ("Limited Availability" if total_qty <= 8 else "In Stock"))
            card_parts = [
                p["name"],
                p.get("brand", "Sainsbury's"),
                f"£{p['price']:.2f}",
                f"{rating_to_stars(p.get('customer_rating', 4.0))} "
                f"{p.get('customer_rating', 4.0):.1f} ({p.get('review_count', 100):,} reviews)",
            ]
            if p.get("best_seller"):
                card_parts.append("🏆 Best Seller")
            if p.get("store_recommended"):
                card_parts.append("💚 Store Recommended")
            if offer_str:
                card_parts.append(offer_str)
            card_parts.append(f"Availability: {avail}")
            card_parts.append(f"Reason:\n{generate_explanation(p)}")
            lines.append("\n".join(card_parts))

        return (
            prefix
            + "Matched Product Catalog Recommendations:\n\n"
            + "\n\n".join(lines)
            + "\n\nYou can order these items directly on the Sainsbury's website "
              "(https://www.sainsburys.co.uk/)."
        )

    def get_active_promotions(self) -> str:
        try:
            from database import get_connection
            import sqlite3
            conn = get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM promotions ORDER BY offer_priority DESC")
            rows = cursor.fetchall()
            conn.close()
        except Exception as e:
            return f"Error loading promotions: {e}"

        if not rows:
            return "There are no active promotions at this moment."

        lines = []
        for r in rows:
            cats  = json.loads(r["applicable_categories"]) if r["applicable_categories"] else []
            prods = json.loads(r["applicable_products"])   if r["applicable_products"]   else []
            app_str = ""
            if cats:
                app_str += f"Categories: {', '.join(cats)}"
            if prods:
                if app_str:
                    app_str += " | "
                app_str += f"Product IDs: {', '.join(prods)}"
            if not app_str:
                app_str = "Store-wide"
            lines.append(
                f"📣 {r['offer_name']} ({r['discount']})\n"
                f"   • Details: {app_str}\n"
                f"   • Coupon Code: {r['coupon_code']}\n"
                f"   • Expiry: {r['expiry']}\n"
                f"   • Requirement: {r['loyalty_requirement']} Member Tier"
            )

        return (
            "Current Active Promotions:\n\n"
            + "\n\n".join(lines)
            + "\n\nApply coupon codes at checkout on the Sainsbury's website "
              "(https://www.sainsburys.co.uk/)."
        )

    def update_customer_address(self, line1: str, city: str, postcode: str = None) -> str:
        data = self._load_customer_data()
        addr = data["customer"]["default_address"]
        addr["line1"] = line1
        addr["city"]  = city
        if postcode:
            addr["postcode"] = postcode
        self._save_customer_data(data)
        return f"Address updated successfully to: {line1}, {city}"

    def issue_refund(
        self, order_id: str, reason: str, amount: float,
        method: str = "Original payment method"
    ) -> str:
        data  = self._load_customer_data()
        order = next(
            (o for o in data["orders"] if o["order_id"].lower() == order_id.lower()),
            None
        )
        if not order:
            return f"Error: Order {order_id} not found."

        import random
        from datetime import date
        ref   = f"REF-{random.randint(20000, 99999)}"
        today = date.today().isoformat()

        order["status"] = "refund_completed"
        order["refund"] = {
            "reason":       reason,
            "requested_on": today,
            "amount":       amount,
            "status":       "completed",
            "method":       method,
            "completed_on": today,
            "reference":    ref,
        }
        self._save_customer_data(data)
        return f"Refund issued successfully. Reference: {ref}, Amount: GBP{amount:.2f}"

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

    def _classify_domain(self, message: str, history: list[dict]) -> str:
        """
        Returns 'retail' or 'general'.

        Classification strategy (in order of priority):
        1. Fast keyword matching on retail keywords → retail
        2. Fast keyword matching on known general topics → general
        3. Lightweight LLM call (single token response) for ambiguous cases
        4. Default to 'retail' (safe fallback for a retail assistant)
        """
        text_lower = message.lower()

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
                                "You are a domain classifier for a UK supermarket chatbot. "
                                "Classify the user's message as exactly one of: retail, general. "
                                "'retail' = questions about grocery products, orders, deliveries, "
                                "refunds, stores, stock, promotions, nutrition labels, allergens, "
                                "or anything Sainsbury's sells or offers. "
                                "'general' = everything else (politics, celebrities, sports, "
                                "history, science, jokes, programming, etc.). "
                                "Respond with exactly one word: retail or general."
                            ),
                        },
                        {"role": "user", "content": message},
                    ],
                    max_tokens=5,
                    temperature=0.0,
                )
                label = res.choices[0].message.content.strip().lower()
                if label in ("retail", "general"):
                    return label
            except Exception as e:
                print(f"[AgentRouter] Domain classification LLM call failed: {e}")

        # 4. Safe default
        return "retail"

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

        Returns:
            str – formatted response if a matching product is found
            None – if not a product-info question, or no matching product found
                   (caller should proceed with full agent routing)
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
        agent_id: str,
        context: str,
        task_query: str,
        history: list[dict],
        extra_instructions: str = "",
    ) -> str:
        """
        Invokes a single Azure AI Foundry agent:
          1. Creates a new thread
          2. Injects customer context as the first user message
          3. Replays recent conversation history
          4. Adds the task query as the final user message
          5. Creates a run (Foundry's system prompt drives behavior)
          6. Polls until complete, handling requires_action tool calls
          7. Returns the agent's reply text

        Args:
            agent_id:          Foundry asst_* agent ID
            context:           Customer/order context block (from build_context_block)
            task_query:        The specific sub-task message for this agent
            history:           Conversation history (last N turns)
            extra_instructions: Optional one-line routing hint injected into context
        """
        if not self._agents_client:
            raise RuntimeError("AgentsClient not initialised.")

        loop = asyncio.get_event_loop()

        # ── 1. Create thread ──────────────────────────────────────────────────
        thread = await loop.run_in_executor(
            None, self._agents_client.threads.create
        )
        thread_id = thread.id

        # ── 2. Inject customer context (first message in thread) ─────────────
        context_msg = context
        if extra_instructions:
            context_msg += f"\n\n[ROUTING NOTE]: {extra_instructions}"

        await loop.run_in_executor(
            None,
            lambda: self._agents_client.messages.create(
                thread_id=thread_id,
                role="user",
                content=context_msg,
            ),
        )

        # ── 3. Replay recent conversation history ────────────────────────────
        for turn in history[-4:]:
            role    = turn.get("role", "user")
            content = turn.get("content", "").strip()
            if role in ("user", "assistant") and content:
                r = role
                await loop.run_in_executor(
                    None,
                    lambda r=r, content=content: self._agents_client.messages.create(
                        thread_id=thread_id,
                        role=r,
                        content=content,
                    ),
                )

        # ── 4. Add the task query ────────────────────────────────────────────
        await loop.run_in_executor(
            None,
            lambda: self._agents_client.messages.create(
                thread_id=thread_id,
                role="user",
                content=task_query,
            ),
        )

        # ── 5. Create run ────────────────────────────────────────────────────
        run = await loop.run_in_executor(
            None,
            lambda: self._agents_client.runs.create(
                thread_id=thread_id,
                agent_id=agent_id,
            ),
        )

        # ── 6. Poll and handle tool calls ────────────────────────────────────
        max_wait    = 120   # seconds
        poll_interval = 1.5 # seconds
        elapsed     = 0.0
        terminal    = {"completed", "failed", "cancelled", "expired"}

        while run.status not in terminal:
            if elapsed >= max_wait:
                print(f"[AgentRouter] Run timed out after {max_wait}s.")
                break

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            run = await loop.run_in_executor(
                None,
                lambda: self._agents_client.runs.get(
                    thread_id=thread_id, run_id=run.id
                ),
            )

            # Handle tool calls
            if run.status == "requires_action":
                tool_outputs = []
                try:
                    calls = run.required_action.submit_tool_outputs.tool_calls
                except AttributeError:
                    calls = []

                for call in calls:
                    func_name = call.function.name
                    try:
                        func_args = json.loads(call.function.arguments)
                    except Exception:
                        func_args = {}

                    # Reload context after any DB mutation
                    result = self._execute_tool(func_name, func_args)

                    tool_outputs.append({
                        "tool_call_id": call.id,
                        "output":       result,
                    })

                if tool_outputs:
                    # Update context with latest customer data after DB mutations
                    updated_customer = self._load_customer_data()
                    self.context = build_context_block(updated_customer)

                    run = await loop.run_in_executor(
                        None,
                        lambda: self._agents_client.runs.submit_tool_outputs(
                            thread_id=thread_id,
                            run_id=run.id,
                            tool_outputs=tool_outputs,
                        ),
                    )

        if run.status == "failed":
            err = getattr(run, "last_error", None)
            raise RuntimeError(f"Foundry run failed: {err}")

        # ── 7. Retrieve assistant reply ───────────────────────────────────────
        messages = await loop.run_in_executor(
            None,
            lambda: list(self._agents_client.messages.list(thread_id=thread_id)),
        )

        # Messages are returned newest-first; find the last assistant message
        for msg in messages:
            if msg.role == "assistant":
                content = msg.content
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if hasattr(block, "text"):
                            val = block.text
                            if hasattr(val, "value"):
                                text_parts.append(val.value)
                            else:
                                text_parts.append(str(val))
                        elif isinstance(block, str):
                            text_parts.append(block)
                    return "\n".join(text_parts).strip()
                return str(content).strip()

        return ""

    # ─────────────────────────────────────────────────────────────────────────
    # Supervisor Routing (calls Foundry Supervisor-Agent for decomposition)
    # ─────────────────────────────────────────────────────────────────────────

    async def _decompose_via_supervisor(
        self, message: str, history: list[dict]
    ) -> list[dict]:
        """
        Calls the Foundry Supervisor-Agent with the user message.
        The Supervisor-Agent's system prompt (in Foundry) instructs it to
        return a JSON list of {agent, task_query} routing objects.

        Falls back to keyword classifier if:
        - Supervisor-Agent ID is not resolved
        - Foundry call fails
        - Response cannot be parsed as valid routing JSON
        """
        supervisor_id = self._agent_ids.get("supervisor")

        if supervisor_id and self._agents_client:
            # Build a structured routing request for the Supervisor-Agent
            history_snippet = "\n".join(
                f"{t['role'].upper()}: {t['content']}"
                for t in history[-5:]
            )
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

        # Keyword fallback
        intent = self._classify_fallback(message)
        return [{"agent": intent, "task_query": message}]

    def _classify_fallback(self, message: str) -> str:
        """Keyword-based routing fallback (no LLM call)."""
        text = message.lower()
        if any(w in text for w in ["refund", "return", "money back", "damaged",
                                    "broken", "spoil", "mould", "expire"]):
            return "refund"
        if any(w in text for w in ["reschedule", "change address", "live tracking",
                                    "tracking link", "tracking url", "what time",
                                    "arriving today", "eta", "driver", "arrival time",
                                    "when will it arrive"]):
            return "delivery"
        if any(w in text for w in [
            "recommend", "suggestion", "suggest", "product", "item", "range",
            "allergen", "gluten", "vegan", "organic", "dairy", "nutrition", "sugar",
            "protein", "lactose", "healthy", "snack", "breakfast",
            "promotion", "discount", "coupon", "offer", "deal", "code", "sale",
            "aisle", "store", "branch", "hours", "timings", "open",
            "stock", "availability", "click and collect", "collect",
            "electronics", "gadget", "fitness", "tracker", "headphone", "kindle",
            "new arrival", "seasonal",
        ]):
            return "store"
        if any(w in text for w in ["driver", "van", "slot", "eta"]):
            return "delivery"
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
        (whose system prompt handles tone, deduplication, and formatting),
        or via a lightweight local concatenation fallback.
        """
        if len(replies) == 1:
            return replies[0]

        supervisor_id = self._agent_ids.get("supervisor")

        if supervisor_id and self._agents_client:
            merge_request = f"Original customer question: {message}\n\n"
            for i, (task, reply) in enumerate(zip(tasks, replies), 1):
                merge_request += f"--- Part {i} (Agent: {task['agent']}) ---\n{reply}\n\n"
            merge_request += (
                "Merge these specialist replies into a single, cohesive, "
                "well-formatted customer response. "
                "Keep all important details. No duplicate greetings or sign-offs."
            )
            try:
                merged = await self._call_foundry_agent(
                    agent_id=supervisor_id,
                    context=self.context,
                    task_query=merge_request,
                    history=[],
                )
                if merged:
                    return merged
            except Exception as e:
                print(f"[AgentRouter] Supervisor merge failed: {e}. Using local merge.")

        # Local fallback: simple join with separator
        return "\n\n".join(replies)

    # ─────────────────────────────────────────────────────────────────────────
    # Validation & Output Sanitization
    # ─────────────────────────────────────────────────────────────────────────

    def _validate_and_sanitize_response(self, message: str, reply: str) -> str:
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
            elif stripped.startswith("*") or stripped.startswith("-"):
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

    async def _run_validation_layer(self, query: str, reply: str) -> str:
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

        return self._validate_and_sanitize_response(query, reply)

    # ─────────────────────────────────────────────────────────────────────────
    # Public Handler – Main Orchestration Entry Point
    # ─────────────────────────────────────────────────────────────────────────

    async def handle(self, message: str, history: list[dict]) -> dict[str, Any]:
        """
        Orchestrates the full request lifecycle:

        1.  Reload customer context from DB (fresh per request)
        2.  Classify domain: retail vs general
        3.  General → route to General-Assistant-Agent (or polite decline)
        4.  Retail → check DB for product-info questions
        5.  Product found in DB → return catalog card directly
        6.  Otherwise → Supervisor-Agent decomposes → specialist agents invoked
        7.  Merge replies (via Supervisor or local join)
        8.  Validate & sanitize output
        9.  Return {reply, intent, sources}
        """
        # ── 1. Refresh context ────────────────────────────────────────────────
        customer_data = self._load_customer_data()
        self.context  = build_context_block(customer_data)

        # ── 2. Domain classification ──────────────────────────────────────────
        domain = self._classify_domain(message, history)
        print(f"[AgentRouter] Domain: {domain} | Message: {message[:80]}")

        # ── 3. General-knowledge questions ────────────────────────────────────
        if domain == "general":
            general_id = self._agent_ids.get("general")
            if general_id and self._agents_client:
                try:
                    reply = await self._call_foundry_agent(
                        agent_id=general_id,
                        context=self.context,
                        task_query=message,
                        history=history,
                    )
                    validated = await self._run_validation_layer(message, reply)
                    return {
                        "reply":   validated,
                        "intent":  "general",
                        "sources": ["general_assistant_agent"],
                    }
                except Exception as e:
                    print(f"[AgentRouter] General-Assistant-Agent call failed: {e}")
                    # Fall through to polite decline

            # Polite decline fallback (no General-Assistant-Agent configured)
            decline = (
                "I'm your Sainsbury's retail assistant, here to help with shopping, "
                "products, orders, deliveries, refunds, stores, and offers. "
                "For general knowledge questions I'm afraid I'm not the right tool — "
                "but feel free to ask me anything retail-related! 😊"
            )
            return {
                "reply":   decline,
                "intent":  "general",
                "sources": ["polite_decline"],
            }

        # ── 4. Retail: product-info DB lookup first ───────────────────────────
        db_result = self._search_db_for_product_question(message)
        if db_result:
            print("[AgentRouter] Answered from product catalog DB directly.")
            validated = await self._run_validation_layer(message, db_result)
            return {
                "reply":   validated,
                "intent":  "store",
                "sources": ["product_catalog_db"],
            }

        # ── 5. Supervisor decomposition (Foundry-driven routing) ─────────────
        tasks = await self._decompose_via_supervisor(message, history)
        print(f"[AgentRouter] Tasks: {tasks}")

        replies = []
        sources = []

        # ── 6. Invoke specialist agents ───────────────────────────────────────
        for task in tasks:
            agent_type = task.get("agent", "order")
            task_query = task.get("task_query", message)
            agent_id   = self._agent_ids.get(agent_type)

            sources.append(f"{agent_type}_agent")

            # ── Foundry agent path ────────────────────────────────────────────
            if agent_id and self._agents_client:
                try:
                    reply = await self._call_foundry_agent(
                        agent_id=agent_id,
                        context=self.context,
                        task_query=task_query,
                        history=history,
                    )
                    replies.append(reply)
                    continue
                except Exception as e:
                    print(f"[AgentRouter] Foundry {agent_type} agent failed: {e}. "
                          "Falling back to OpenAI direct.")

            # ── OpenAI direct fallback (no Foundry agent available) ───────────
            if self._openai_client:
                try:
                    deployment = os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-4o")
                    messages_payload = [
                        {"role": "system", "content": self.context},
                    ]
                    for turn in history[-4:]:
                        r = turn.get("role", "user")
                        c = turn.get("content", "").strip()
                        if r in ("user", "assistant") and c:
                            messages_payload.append({"role": r, "content": c})
                    messages_payload.append({"role": "user", "content": task_query})

                    # Determine which tools to pass for this agent type
                    tools = self._agent_tools.get(agent_type, [])
                    resp  = self._openai_client.chat.completions.create(
                        model=deployment,
                        messages=messages_payload,
                        tools=tools if tools else None,
                        tool_choice="auto" if tools else None,
                        max_tokens=800,
                        temperature=0.0,
                    )
                    msg = resp.choices[0].message

                    # Handle tool calls in fallback path
                    if msg.tool_calls:
                        messages_payload.append(msg)
                        for tc in msg.tool_calls:
                            fname  = tc.function.name
                            fargs  = json.loads(tc.function.arguments)
                            result = self._execute_tool(fname, fargs)
                            messages_payload.append({
                                "role":         "tool",
                                "tool_call_id": tc.id,
                                "name":         fname,
                                "content":      result,
                            })
                        # Refresh context after possible mutations
                        updated    = self._load_customer_data()
                        self.context = build_context_block(updated)
                        messages_payload[0]["content"] = self.context

                        final = self._openai_client.chat.completions.create(
                            model=deployment,
                            messages=messages_payload,
                            max_tokens=800,
                            temperature=0.0,
                        )
                        replies.append(final.choices[0].message.content.strip())
                    else:
                        replies.append(msg.content.strip())

                except Exception as e:
                    print(f"[AgentRouter] OpenAI fallback failed for {agent_type}: {e}")
                    replies.append(
                        f"I'm sorry, I had trouble processing your {agent_type} request. "
                        "Please try again or contact our support team."
                    )
            else:
                replies.append(
                    f"I'm sorry, the {agent_type} specialist is currently unavailable. "
                    "Please try again shortly."
                )

        if not replies:
            replies = ["I'm sorry, I was unable to process your request. Please try again."]

        # ── 7. Merge replies ──────────────────────────────────────────────────
        merged = await self._merge_replies(message, tasks, replies)

        # ── 8. Validate & sanitize ────────────────────────────────────────────
        validated = await self._run_validation_layer(message, merged)

        # ── 9. Return result ──────────────────────────────────────────────────
        primary_intent = tasks[0]["agent"] if tasks else "order"
        return {
            "reply":   validated,
            "intent":  primary_intent,
            "sources": sources,
        }