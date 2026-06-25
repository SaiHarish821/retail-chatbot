"""
Retail AI Assistant – Local Database Tools and Calculations
"""
import os
import re
import json
import math
import random
import sqlite3
from datetime import date
from typing import Optional, Any

# ─────────────────────────────────────────────────────────────────────────────
# 1. Calculation Helpers
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


def clean_name_for_matching(name: str) -> str:
    # Remove volume/weight descriptors at the end (e.g. 2L, 800g, 12pk, 500ml, etc.)
    cleaned = re.sub(r'\s+\d+(?:l|g|pk|ml|pack|kg|%)\s*$', '', name, flags=re.IGNORECASE)
    cleaned = cleaned.replace("approx", "").strip()
    return cleaned


# ─────────────────────────────────────────────────────────────────────────────
# 2. Local database Query Tools (to be bound as AgentRouter instance methods)
# ─────────────────────────────────────────────────────────────────────────────

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
    products_json_list = []
    for p, _ in matched[:limit]:
        disc      = p.get("discount", {})
        if isinstance(disc, str):
            try:
                disc = json.loads(disc)
            except Exception:
                disc = {}
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

        # Build product entry for visual UI
        product_entry = {
            "id": p["product_id"],
            "name": p["name"],
            "brand": p.get("brand", "Sainsbury's"),
            "price": p["price"],
            "customer_rating": p.get("customer_rating", 4.0),
            "review_count": p.get("review_count", 100),
            "best_seller": bool(p.get("best_seller")),
            "store_recommended": bool(p.get("store_recommended")),
            "is_on_promotion": bool(p.get("is_on_promotion")),
            "promotion_detail": offer_str,
            "availability": avail,
            "aisle": p.get("aisle", "N/A"),
            "explanation": generate_explanation(p),
            "category": p.get("category", "")
        }
        products_json_list.append(product_entry)

    grid_json = json.dumps(products_json_list)
    grid_xml = f"<product-grid>{grid_json}</product-grid>"

    return (
        prefix
        + "Matched Product Catalog Recommendations:\n\n"
        + "\n\n".join(lines)
        + "\n\n" + grid_xml
        + "\n\nYou can order these items directly on the Sainsbury's website "
          "(https://www.sainsburys.co.uk/)."
    )


def get_active_promotions(self) -> str:
    try:
        from database import get_connection
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


def append_product_grid_if_mentioned(self, reply: str) -> str:
    try:
        data = self._load_inventory_data()
        products = data.get("inventory", [])
    except Exception:
        return reply

    matched_products = []
    reply_lower = reply.lower()
    
    # Sort products by length of name descending, so longer matches are checked first
    sorted_products = sorted(products, key=lambda x: len(x["name"]), reverse=True)
    
    for p in sorted_products:
        clean_name = clean_name_for_matching(p["name"])
        # Match using word boundaries to avoid matching short substrings inside other words
        # e.g., 'rice' matching inside 'price' or 'butter' matching inside 'butterfly'
        pattern = r'\b' + re.escape(clean_name.lower()) + r'\b'
        if re.search(pattern, reply_lower):
            if p not in matched_products:
                matched_products.append(p)
                
    if matched_products:
        # Cap at 3 product cards to keep the UI clean
        matched_products = matched_products[:3]
        products_json_list = []
        for p in matched_products:
            disc = p.get("discount", {})
            if isinstance(disc, str):
                try:
                    disc = json.loads(disc)
                except Exception:
                    disc = {}
            offer_str = disc.get("offer_text", "") if disc.get("is_on_sale") else p.get("promotion_detail", "")
            total_qty = sum(sinfo.get("quantity", 0) for sinfo in p.get("stock", {}).values())
            avail     = ("Out of Stock" if total_qty == 0
                         else ("Limited Availability" if total_qty <= 8 else "In Stock"))
            
            explanation = ""
            if p.get("best_seller"):
                explanation = f"One of our best-selling items, rated {p['customer_rating']:.1f} stars."
            elif p.get("store_recommended"):
                explanation = "Highly recommended by our store managers."
            elif p.get("is_on_promotion"):
                explanation = f"Currently on promotion: {offer_str}."
            else:
                explanation = p.get("description", "")[:120] + "..."

            products_json_list.append({
                "id": p["product_id"],
                "name": p["name"],
                "brand": p.get("brand", "Sainsbury's"),
                "price": p["price"],
                "customer_rating": p.get("customer_rating", 4.0),
                "review_count": p.get("review_count", 100),
                "best_seller": bool(p.get("best_seller")),
                "store_recommended": bool(p.get("store_recommended")),
                "is_on_promotion": bool(p.get("is_on_promotion")),
                "promotion_detail": offer_str,
                "availability": avail,
                "aisle": p.get("aisle", "N/A"),
                "explanation": explanation,
                "category": p.get("category", "")
            })
            
        grid_json = json.dumps(products_json_list)
        grid_xml = f"<product-grid>{grid_json}</product-grid>"
        return reply + "\n\n" + grid_xml

    return reply
