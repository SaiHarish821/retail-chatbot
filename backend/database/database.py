import sqlite3
import os
import json
import shutil

ORIGINAL_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "mock_data", "retail_chatbot.db"))

# Detect Vercel or AWS Lambda serverless execution environments
if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    DB_PATH = "/tmp/retail_chatbot.db"
    # Copy original seeded database to writeable /tmp path if it doesn't exist yet
    if not os.path.exists(DB_PATH) and os.path.exists(ORIGINAL_DB_PATH):
        try:
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            shutil.copy2(ORIGINAL_DB_PATH, DB_PATH)
            print(f"[Database] Copied SQLite database to writeable /tmp path: {DB_PATH}")
        except Exception as e:
            print(f"[Database] Failed to copy database to /tmp: {e}")
            DB_PATH = ORIGINAL_DB_PATH
else:
    DB_PATH = ORIGINAL_DB_PATH

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    # Ensure parent directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # Create customer table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customer (
            id TEXT PRIMARY KEY,
            name TEXT,
            email TEXT,
            phone TEXT,
            loyalty_tier TEXT,
            loyalty_points INTEGER,
            registered_since TEXT,
            address_line1 TEXT,
            address_city TEXT,
            address_postcode TEXT,
            address_country TEXT
        )
    """)
    
    # Create orders table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            customer_id TEXT,
            date TEXT,
            status TEXT,
            total REAL,
            payment_method TEXT,
            delivery_method TEXT,
            delivery_slot TEXT,
            delivery_delivered_at TEXT,
            delivery_driver TEXT,
            delivery_current_stop INTEGER,
            delivery_total_stops INTEGER,
            delivery_eta TEXT,
            delivery_live_tracking_url TEXT,
            delivery_store TEXT,
            collected_at TEXT,
            FOREIGN KEY (customer_id) REFERENCES customer (id)
        )
    """)
    
    # Create order_items table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT,
            name TEXT,
            qty INTEGER,
            price REAL,
            FOREIGN KEY (order_id) REFERENCES orders (order_id)
        )
    """)
    
    # Create refunds table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS refunds (
            order_id TEXT PRIMARY KEY,
            reason TEXT,
            requested_on TEXT,
            amount REAL,
            status TEXT,
            method TEXT,
            completed_on TEXT,
            reference TEXT,
            FOREIGN KEY (order_id) REFERENCES orders (order_id)
        )
    """)

    # Create stores table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stores (
            id TEXT PRIMARY KEY,
            name TEXT,
            address TEXT,
            lat REAL,
            lng REAL,
            type TEXT,
            phone TEXT,
            opening_hours TEXT
        )
    """)

    # Create products table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY,
            name TEXT,
            description TEXT,
            price REAL,
            category TEXT,
            subcategory TEXT,
            brand TEXT,
            sku TEXT,
            barcode TEXT,
            aisle TEXT,
            manufacture_date TEXT,
            expiry_date TEXT,
            shelf_life_days INTEGER,
            storage TEXT,
            country_of_origin TEXT,
            certifications TEXT,
            allergens TEXT,
            nutritional_info TEXT,
            tags TEXT,
            weight_volume TEXT,
            is_on_promotion INTEGER,
            promotion_detail TEXT,
            nectar_points INTEGER,
            online_available INTEGER,
            click_and_collect INTEGER,
            
            -- Rich metadata extensions
            discount TEXT,
            customer_rating REAL,
            review_count INTEGER,
            best_seller INTEGER,
            store_recommended INTEGER,
            staff_pick INTEGER,
            healthy_choice INTEGER,
            organic INTEGER,
            vegan INTEGER,
            gluten_free INTEGER,
            sugar_free INTEGER,
            high_protein INTEGER,
            lactose_free INTEGER,
            diet_tags TEXT,
            popularity_score INTEGER,
            frequently_bought_together TEXT,
            customer_favorite INTEGER,
            seasonal_offer INTEGER,
            new_arrival INTEGER,
            available INTEGER
        )
    """)

    # Create product_stock table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS product_stock (
            product_id TEXT,
            store_id TEXT,
            quantity INTEGER,
            PRIMARY KEY (product_id, store_id),
            FOREIGN KEY (product_id) REFERENCES products (id),
            FOREIGN KEY (store_id) REFERENCES stores (id)
        )
    """)

    # Create promotions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS promotions (
            offer_id TEXT PRIMARY KEY,
            offer_name TEXT,
            discount TEXT,
            applicable_categories TEXT,
            applicable_products TEXT,
            coupon_code TEXT,
            expiry TEXT,
            loyalty_requirement TEXT,
            offer_priority INTEGER
        )
    """)
    
    conn.commit()
    conn.close()

def decorate_product(item: dict) -> dict:
    import hashlib
    p_id = item["product_id"]
    name_lower = item["name"].lower()
    cat_lower = item["category"].lower()
    price = item["price"]

    # Deterministic hash function for rating/reviews/popularity so they are reproducible
    h = int(hashlib.md5(p_id.encode('utf-8')).hexdigest(), 16)
    
    # rating between 4.0 and 4.9
    rating = round(4.0 + (h % 10) * 0.1, 1)
    # reviews between 120 and 2400
    reviews = 120 + (h % 2280)
    # popularity score between 60 and 99
    popularity = 60 + (h % 40)
    
    best_seller = 1 if popularity > 82 else 0
    store_recommended = 1 if (h % 3 == 0) else 0
    staff_pick = 1 if (h % 8 == 0) else 0
    
    # Healthy / organic checks
    is_organic = 1 if "organic" in name_lower else 0
    healthy = 1 if (cat_lower in ["produce", "dairy", "fresh meat & fish"] or is_organic or "spinach" in name_lower) else 0
    
    # Vegan / gluten-free / sugar-free checks
    is_meat = any(w in name_lower for w in ["chicken", "salmon", "beef", "pork", "meat", "ham", "turkey"])
    is_dairy = any(w in name_lower for w in ["milk", "cheese", "yoghurt", "butter", "cream", "croissant"])
    is_egg = "egg" in name_lower
    
    vegan = 1 if (cat_lower in ["produce", "pantry", "drinks"] and not (is_meat or is_dairy or is_egg)) else 0
    
    is_wheat = any(w in name_lower for w in ["bread", "croissant", "pasta", "flour", "wheat", "fusilli"])
    gluten_free = 1 if (not is_wheat and cat_lower in ["produce", "drinks", "fresh meat & fish", "dairy"]) else 0
    
    is_sweet = any(w in name_lower for w in ["juice", "chocolate", "sweet", "cereal", "sugar", "biscuit", "cookie"])
    sugar_free = 1 if (not is_sweet and cat_lower in ["produce", "fresh meat & fish", "dairy", "pantry"]) else 0
    
    # High-protein
    high_protein = 1 if (is_meat or is_egg or "cheese" in name_lower or "yoghurt" in name_lower or "protein" in name_lower) else 0
    
    # Lactose-free
    lactose_free = 0 if is_dairy else 1

    # Diet tags
    diet_tags_list = []
    if healthy: diet_tags_list.append("Healthy")
    if is_organic: diet_tags_list.append("Organic")
    if vegan: diet_tags_list.append("Vegan")
    if gluten_free: diet_tags_list.append("Gluten Free")
    if sugar_free: diet_tags_list.append("Sugar Free")
    if high_protein: diet_tags_list.append("High Protein")
    if lactose_free: diet_tags_list.append("Lactose Free")
    
    # Discount / sale
    is_on_promotion = item.get("is_on_promotion", False)
    
    discount_dict = {
        "is_on_sale": False,
        "discount_percentage": 0,
        "old_price": price,
        "new_price": price,
        "offer_text": "",
        "offer_end_date": ""
    }
    
    if is_on_promotion:
        pct = 10 + (h % 3) * 10  # 10%, 20%, 30%
        old_price = round(price / (1.0 - (pct / 100.0)), 2)
        discount_dict = {
            "is_on_sale": True,
            "discount_percentage": pct,
            "old_price": old_price,
            "new_price": price,
            "offer_text": f"{pct}% OFF",
            "offer_end_date": "2026-07-15"
        }
    
    # Frequently bought together
    frequently_bought = ["Milk", "Bread"]
    if "milk" in name_lower:
        frequently_bought = ["Sourdough Bread 800g", "Butter Unsalted 250g"]
    elif "bread" in name_lower:
        frequently_bought = ["Organic Whole Milk 2L", "Cheddar Cheese 400g"]
    elif "pasta" in name_lower:
        frequently_bought = ["Tomato Passata 690g", "Cheddar Cheese 400g"]
    elif "chicken" in name_lower:
        frequently_bought = ["Baby Spinach 200g", "Olive Oil Extra Virgin 500ml"]
        
    return {
        "discount": json.dumps(discount_dict),
        "customer_rating": rating,
        "review_count": reviews,
        "best_seller": best_seller,
        "store_recommended": store_recommended,
        "staff_pick": staff_pick,
        "healthy_choice": healthy,
        "organic": is_organic,
        "vegan": vegan,
        "gluten_free": gluten_free,
        "sugar_free": sugar_free,
        "high_protein": high_protein,
        "lactose_free": lactose_free,
        "diet_tags": json.dumps(diet_tags_list),
        "popularity_score": popularity,
        "frequently_bought_together": json.dumps(frequently_bought),
        "customer_favorite": 1 if rating >= 4.6 else 0,
        "seasonal_offer": 1 if (h % 11 == 0) else 0,
        "new_arrival": 1 if (h % 7 == 0) else 0,
        "available": 1
    }

def check_needs_reseed() -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='promotions'")
    has_promotions = cursor.fetchone() is not None
    if not has_promotions:
        conn.close()
        return True
    cursor.execute("PRAGMA table_info(products)")
    columns = [col[1] for col in cursor.fetchall()]
    if "customer_rating" not in columns:
        conn.close()
        return True
    conn.close()
    return False

def seed_db(force=False):
    if force or check_needs_reseed():
        print("[Database] Schema mismatch or force flag. Dropping tables for re-seeding...")
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS product_stock")
        cursor.execute("DROP TABLE IF EXISTS products")
        cursor.execute("DROP TABLE IF EXISTS stores")
        cursor.execute("DROP TABLE IF EXISTS promotions")
        cursor.execute("DROP TABLE IF EXISTS refunds")
        cursor.execute("DROP TABLE IF EXISTS order_items")
        cursor.execute("DROP TABLE IF EXISTS orders")
        cursor.execute("DROP TABLE IF EXISTS customer")
        conn.commit()
        conn.close()
        init_db()

    conn = get_connection()
    cursor = conn.cursor()
    
    # Check if customer table is seeded
    cursor.execute("SELECT COUNT(*) FROM customer")
    customer_seeded = cursor.fetchone()[0] > 0

    # Check if products table is seeded
    cursor.execute("SELECT COUNT(*) FROM products")
    products_seeded = cursor.fetchone()[0] > 0
    
    if customer_seeded and products_seeded:
        conn.close()
        return  # already seeded
        
    # Import seed data dynamically to avoid import-time dependency or circular imports
    from .seed_data import CUSTOMER_SEED, INVENTORY_SEED
    
    if not customer_seeded:
        cust = CUSTOMER_SEED["customer"]
        addr = cust.get("default_address", {})
        
        cursor.execute("""
            INSERT INTO customer (
                id, name, email, phone, loyalty_tier, loyalty_points, registered_since,
                address_line1, address_city, address_postcode, address_country
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            cust["id"], cust["name"], cust["email"], cust["phone"], cust["loyalty_tier"],
            cust["loyalty_points"], cust["registered_since"],
            addr.get("line1"), addr.get("city"), addr.get("postcode"), addr.get("country")
        ))
        
        for o in CUSTOMER_SEED.get("orders", []):
            deliv = o.get("delivery") or {}
            cursor.execute("""
                INSERT INTO orders (
                    order_id, customer_id, date, status, total, payment_method,
                    delivery_method, delivery_slot, delivery_delivered_at, delivery_driver,
                    delivery_current_stop, delivery_total_stops, delivery_eta,
                    delivery_live_tracking_url, delivery_store, collected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                o["order_id"], cust["id"], o["date"], o["status"], o["total"], o["payment_method"],
                deliv.get("method"), deliv.get("slot"), deliv.get("delivered_at"), deliv.get("driver"),
                deliv.get("current_stop"), deliv.get("total_stops"), deliv.get("eta"),
                deliv.get("live_tracking_url"), deliv.get("store"), deliv.get("collected_at")
            ))
            
            for item in o.get("items", []):
                cursor.execute("""
                    INSERT INTO order_items (order_id, name, qty, price)
                    VALUES (?, ?, ?, ?)
                """, (o["order_id"], item["name"], item["qty"], item["price"]))
                
            r = o.get("refund")
            if r:
                cursor.execute("""
                    INSERT INTO refunds (
                        order_id, reason, requested_on, amount, status, method, completed_on, reference
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    o["order_id"], r["reason"], r["requested_on"], r["amount"],
                    r["status"], r["method"], r.get("completed_on"), r["reference"]
                ))

    if not products_seeded:
        metadata = INVENTORY_SEED.get("metadata", {})
        stores = metadata.get("stores", {})
        
        for store_id, s in stores.items():
            cursor.execute("""
                INSERT OR IGNORE INTO stores (
                    id, name, address, lat, lng, type, phone, opening_hours
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                store_id, s["name"], s["address"], s["lat"], s["lng"],
                s["type"], s["phone"], json.dumps(s.get("opening_hours"))
            ))

        for item in INVENTORY_SEED.get("inventory", []):
            p_id = item["product_id"]
            
            certifications_json = json.dumps(item.get("certifications", []))
            allergens_json = json.dumps(item.get("allergens", []))
            nutritional_info_json = json.dumps(item.get("nutritional_info", {}))
            tags_json = json.dumps(item.get("tags", []))
            promotion_detail_json = json.dumps(item.get("promotion_detail")) if "promotion_detail" in item else None

            # Decorate product to get extended attributes
            dec = decorate_product(item)

            cursor.execute("""
                INSERT OR IGNORE INTO products (
                    id, name, description, price, category, subcategory, brand, sku, barcode, aisle,
                    manufacture_date, expiry_date, shelf_life_days, storage, country_of_origin,
                    certifications, allergens, nutritional_info, tags, weight_volume,
                    is_on_promotion, promotion_detail, nectar_points, online_available, click_and_collect,
                    discount, customer_rating, review_count, best_seller, store_recommended, staff_pick,
                    healthy_choice, organic, vegan, gluten_free, sugar_free, high_protein, lactose_free,
                    diet_tags, popularity_score, frequently_bought_together, customer_favorite,
                    seasonal_offer, new_arrival, available
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                p_id, item["name"], item["description"], item["price"], item["category"],
                item.get("subcategory"), item.get("brand"), item.get("sku"), item.get("barcode"), item.get("aisle"),
                item.get("manufacture_date"), item.get("expiry_date"), item.get("shelf_life_days"),
                item.get("storage"), item.get("country_of_origin"), certifications_json, allergens_json,
                nutritional_info_json, tags_json, item.get("weight_volume"),
                1 if item.get("is_on_promotion") else 0, promotion_detail_json,
                item.get("nectar_points"), 1 if item.get("online_available") else 0,
                1 if item.get("click_and_collect") else 0,
                dec["discount"], dec["customer_rating"], dec["review_count"],
                dec["best_seller"], dec["store_recommended"], dec["staff_pick"],
                dec["healthy_choice"], dec["organic"], dec["vegan"], dec["gluten_free"],
                dec["sugar_free"], dec["high_protein"], dec["lactose_free"],
                dec["diet_tags"], dec["popularity_score"], dec["frequently_bought_together"],
                dec["customer_favorite"], dec["seasonal_offer"], dec["new_arrival"],
                dec["available"]
            ))

            for store_id, s_stock in item.get("stock", {}).items():
                cursor.execute("""
                    INSERT OR IGNORE INTO product_stock (product_id, store_id, quantity)
                    VALUES (?, ?, ?)
                """, (p_id, store_id, s_stock.get("quantity", 0)))
                
        # Seed promotions table
        promotions_list = [
            ("OFF-001", "20% OFF Dairy", "20% OFF", json.dumps(["Dairy"]), json.dumps([]), "DAIRY20", "2026-07-15", "None", 1),
            ("OFF-002", "Weekend Organic Sale", "15% OFF", json.dumps([]), json.dumps(["PRD-001", "PRD-003", "PRD-005"]), "ORGANIC15", "2026-06-30", "None", 2),
            ("OFF-003", "Gold Member Special", "10% OFF", json.dumps([]), json.dumps([]), "GOLD10", "2026-12-31", "Gold", 3),
            ("OFF-004", "Weekend Offer", "10% OFF", json.dumps(["Produce", "Bakery"]), json.dumps([]), "WEEKEND10", "2026-06-21", "None", 1),
            ("OFF-005", "Buy 1 Get 1 (BOGO)", "BOGO", json.dumps([]), json.dumps(["PRD-002", "PRD-012"]), "BOGO", "2026-07-31", "None", 2),
        ]
        
        for p in promotions_list:
            cursor.execute("""
                INSERT OR IGNORE INTO promotions (
                    offer_id, offer_name, discount, applicable_categories, applicable_products,
                    coupon_code, expiry, loyalty_requirement, offer_priority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, p)
            
    conn.commit()
    conn.close()

def load_db_inventory_data() -> dict:
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. Fetch stores
    cursor.execute("SELECT * FROM stores")
    store_rows = cursor.fetchall()
    stores = {}
    for row in store_rows:
        s_id = row["id"]
        stores[s_id] = {
            "name": row["name"],
            "address": row["address"],
            "lat": row["lat"],
            "lng": row["lng"],
            "type": row["type"],
            "phone": row["phone"],
            "opening_hours": json.loads(row["opening_hours"]) if row["opening_hours"] else {}
        }
        
    # 2. Fetch products
    cursor.execute("SELECT * FROM products")
    product_rows = cursor.fetchall()
    
    # 3. Fetch all stock
    cursor.execute("SELECT * FROM product_stock")
    stock_rows = cursor.fetchall()
    stock_map = {}
    for row in stock_rows:
        p_id = row["product_id"]
        s_id = row["store_id"]
        qty = row["quantity"]
        if p_id not in stock_map:
            stock_map[p_id] = {}
        stock_map[p_id][s_id] = qty
        
    inventory = []
    for prow in product_rows:
        p_id = prow["id"]
        p_stock = {}
        for s_id, s_info in stores.items():
            qty = stock_map.get(p_id, {}).get(s_id, 0)
            p_stock[s_id] = {
                "quantity": qty,
                "in_stock": qty > 0,
                "low_stock": 0 < qty <= 8,
                "store_name": s_info["name"],
                "store_type": s_info["type"],
                "address": s_info["address"],
                "phone": s_info["phone"],
                "lat": s_info["lat"],
                "lng": s_info["lng"],
                "opening_hours": s_info["opening_hours"]
            }
            
        certifications = []
        if prow["certifications"]:
            try:
                certifications = json.loads(prow["certifications"])
            except Exception:
                pass
                
        allergens = []
        if prow["allergens"]:
            try:
                allergens = json.loads(prow["allergens"])
            except Exception:
                pass
                
        nutritional_info = {}
        if prow["nutritional_info"]:
            try:
                nutritional_info = json.loads(prow["nutritional_info"])
            except Exception:
                pass
                
        tags = []
        if prow["tags"]:
            try:
                tags = json.loads(prow["tags"])
            except Exception:
                pass
                
        promotion_detail = None
        if prow["promotion_detail"]:
            try:
                promotion_detail = json.loads(prow["promotion_detail"])
            except Exception:
                pass
                
        prod_dict = {
            "product_id": p_id,
            "name": prow["name"],
            "description": prow["description"],
            "price": prow["price"],
            "category": prow["category"],
            "subcategory": prow["subcategory"],
            "brand": prow["brand"],
            "sku": prow["sku"],
            "barcode": prow["barcode"],
            "aisle": prow["aisle"],
            "stock": p_stock,
            "manufacture_date": prow["manufacture_date"],
            "expiry_date": prow["expiry_date"],
            "shelf_life_days": prow["shelf_life_days"],
            "storage": prow["storage"],
            "country_of_origin": prow["country_of_origin"],
            "certifications": certifications,
            "allergens": allergens,
            "nutritional_info": nutritional_info,
            "tags": tags,
            "weight_volume": prow["weight_volume"],
            "is_on_promotion": bool(prow["is_on_promotion"]),
            "nectar_points": prow["nectar_points"],
            "online_available": bool(prow["online_available"]),
            "click_and_collect": bool(prow["click_and_collect"]),
            
            # Rich metadata extensions
            "discount": json.loads(prow["discount"]) if prow["discount"] else {},
            "customer_rating": prow["customer_rating"],
            "review_count": prow["review_count"],
            "best_seller": bool(prow["best_seller"]),
            "store_recommended": bool(prow["store_recommended"]),
            "staff_pick": bool(prow["staff_pick"]),
            "healthy_choice": bool(prow["healthy_choice"]),
            "organic": bool(prow["organic"]),
            "vegan": bool(prow["vegan"]),
            "gluten_free": bool(prow["gluten_free"]),
            "sugar_free": bool(prow["sugar_free"]),
            "high_protein": bool(prow["high_protein"]),
            "lactose_free": bool(prow["lactose_free"]),
            "diet_tags": json.loads(prow["diet_tags"]) if prow["diet_tags"] else [],
            "popularity_score": prow["popularity_score"],
            "frequently_bought_together": json.loads(prow["frequently_bought_together"]) if prow["frequently_bought_together"] else [],
            "customer_favorite": bool(prow["customer_favorite"]),
            "seasonal_offer": bool(prow["seasonal_offer"]),
            "new_arrival": bool(prow["new_arrival"]),
            "available": bool(prow["available"])
        }
        if promotion_detail is not None:
            prod_dict["promotion_detail"] = promotion_detail
            
        inventory.append(prod_dict)
        
    conn.close()
    
    return {
        "metadata": {
            "version": "2.0",
            "generated": "2026-06-18",
            "total_products": len(inventory),
            "stores": stores
        },
        "inventory": inventory
    }

def load_db_customer_data() -> dict:
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Load customer
    cursor.execute("SELECT * FROM customer LIMIT 1")
    cust_row = cursor.fetchone()
    if not cust_row:
        conn.close()
        return {}
        
    cust_dict = dict(cust_row)
    customer_data = {
        "customer": {
            "id": cust_dict["id"],
            "name": cust_dict["name"],
            "email": cust_dict["email"],
            "phone": cust_dict["phone"],
            "loyalty_tier": cust_dict["loyalty_tier"],
            "loyalty_points": cust_dict["loyalty_points"],
            "registered_since": cust_dict["registered_since"],
            "default_address": {
                "line1": cust_dict["address_line1"],
                "city": cust_dict["address_city"],
                "postcode": cust_dict["address_postcode"],
                "country": cust_dict["address_country"]
            }
        },
        "orders": []
    }
    
    # Load orders
    cursor.execute("SELECT * FROM orders WHERE customer_id = ?", (cust_dict["id"],))
    order_rows = cursor.fetchall()
    
    for orow in order_rows:
        o_dict = dict(orow)
        order_id = o_dict["order_id"]
        
        # Load items
        cursor.execute("SELECT name, qty, price FROM order_items WHERE order_id = ?", (order_id,))
        item_rows = cursor.fetchall()
        items = [dict(irow) for irow in item_rows]
        
        # Load refund
        cursor.execute("SELECT * FROM refunds WHERE order_id = ?", (order_id,))
        ref_row = cursor.fetchone()
        refund = dict(ref_row) if ref_row else None
        if refund:
            refund.pop("order_id", None)
            
        # Reconstruct delivery object
        delivery = {}
        if o_dict.get("delivery_method"):
            delivery["method"] = o_dict["delivery_method"]
            delivery["slot"] = o_dict["delivery_slot"]
            delivery["delivered_at"] = o_dict["delivery_delivered_at"]
            delivery["driver"] = o_dict["delivery_driver"]
            delivery["current_stop"] = o_dict["delivery_current_stop"]
            delivery["total_stops"] = o_dict["delivery_total_stops"]
            delivery["eta"] = o_dict["delivery_eta"]
            delivery["live_tracking_url"] = o_dict["delivery_live_tracking_url"]
            delivery["store"] = o_dict["delivery_store"]
            delivery["collected_at"] = o_dict["collected_at"]
        else:
            delivery = None
            
        order_obj = {
            "order_id": order_id,
            "date": o_dict["date"],
            "status": o_dict["status"],
            "items": items,
            "total": o_dict["total"],
            "payment_method": o_dict["payment_method"],
            "delivery": delivery,
            "refund": refund
        }
        customer_data["orders"].append(order_obj)
        
    conn.close()
    return customer_data

def save_db_customer_data(data: dict):
    conn = get_connection()
    cursor = conn.cursor()
    
    cust = data["customer"]
    addr = cust.get("default_address", {})
    
    # Update customer info
    cursor.execute("""
        INSERT INTO customer (
            id, name, email, phone, loyalty_tier, loyalty_points, registered_since,
            address_line1, address_city, address_postcode, address_country
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,
            email=excluded.email,
            phone=excluded.phone,
            loyalty_tier=excluded.loyalty_tier,
            loyalty_points=excluded.loyalty_points,
            registered_since=excluded.registered_since,
            address_line1=excluded.address_line1,
            address_city=excluded.address_city,
            address_postcode=excluded.address_postcode,
            address_country=excluded.address_country
    """, (
        cust["id"], cust["name"], cust["email"], cust["phone"], cust["loyalty_tier"],
        cust["loyalty_points"], cust["registered_since"],
        addr.get("line1"), addr.get("city"), addr.get("postcode"), addr.get("country")
    ))
    
    for o in data.get("orders", []):
        deliv = o.get("delivery") or {}
        # Update/insert orders
        cursor.execute("""
            INSERT INTO orders (
                order_id, customer_id, date, status, total, payment_method,
                delivery_method, delivery_slot, delivery_delivered_at, delivery_driver,
                delivery_current_stop, delivery_total_stops, delivery_eta,
                delivery_live_tracking_url, delivery_store, collected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(order_id) DO UPDATE SET
                status=excluded.status,
                total=excluded.total,
                payment_method=excluded.payment_method,
                delivery_method=excluded.delivery_method,
                delivery_slot=excluded.delivery_slot,
                delivery_delivered_at=excluded.delivery_delivered_at,
                delivery_driver=excluded.delivery_driver,
                delivery_current_stop=excluded.delivery_current_stop,
                delivery_total_stops=excluded.delivery_total_stops,
                delivery_eta=excluded.delivery_eta,
                delivery_live_tracking_url=excluded.delivery_live_tracking_url,
                delivery_store=excluded.delivery_store,
                collected_at=excluded.collected_at
        """, (
            o["order_id"], cust["id"], o["date"], o["status"], o["total"], o["payment_method"],
            deliv.get("method"), deliv.get("slot"), deliv.get("delivered_at"), deliv.get("driver"),
            deliv.get("current_stop"), deliv.get("total_stops"), deliv.get("eta"),
            deliv.get("live_tracking_url"), deliv.get("store"), deliv.get("collected_at")
        ))
        
        # Rewrite items
        cursor.execute("DELETE FROM order_items WHERE order_id = ?", (o["order_id"],))
        for item in o.get("items", []):
            cursor.execute("""
                INSERT INTO order_items (order_id, name, qty, price)
                VALUES (?, ?, ?, ?)
            """, (o["order_id"], item["name"], item["qty"], item["price"]))
            
        # Update/insert refund
        r = o.get("refund")
        if r:
            cursor.execute("""
                INSERT INTO refunds (
                    order_id, reason, requested_on, amount, status, method, completed_on, reference
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    reason=excluded.reason,
                    requested_on=excluded.requested_on,
                    amount=excluded.amount,
                    status=excluded.status,
                    method=excluded.method,
                    completed_on=excluded.completed_on,
                    reference=excluded.reference
            """, (
                o["order_id"], r["reason"], r["requested_on"], r["amount"],
                r["status"], r["method"], r.get("completed_on"), r["reference"]
            ))
        else:
            cursor.execute("DELETE FROM refunds WHERE order_id = ?", (o["order_id"],))
            
    conn.commit()
    conn.close()
