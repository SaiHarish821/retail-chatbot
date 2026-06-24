import sys
sys.path.insert(0, '.')
import os
os.environ.setdefault('AZURE_AI_FOUNDRY_PROJECT_ENDPOINT', '')
os.environ.setdefault('AZURE_AI_FOUNDRY_API_KEY', '')
os.environ.setdefault('AZURE_OPENAI_ENDPOINT', '')
os.environ.setdefault('AZURE_TENANT_ID', '')

from database import load_db_customer_data

data = load_db_customer_data()

# Simulate what _call_voice_openai does
cust = data.get('customer') or data
orders = data.get('orders', [])
name = cust.get('name', 'there')
loyalty = cust.get('loyalty_points', 0)
email = cust.get('email', '')
print(f"name: {name}, loyalty: {loyalty}, email: {email}")

if orders:
    o = orders[-1]
    delivery = o.get('delivery') or {}
    if isinstance(delivery, str):
        delivery = {}
    refund = o.get('refund') or {}
    if isinstance(refund, str):
        refund = {}
    items = o.get('items') or []
    items_str = ""
    if isinstance(items, list):
        items_str = ", ".join(
            f"{it.get('name','item')} x{it.get('qty', it.get('quantity', 1))}"
            for it in items[:4]
        )
    print(f"items_str: {items_str}")
    print(f"total: {o.get('total', o.get('total_price', 0))}")
    
print("SUCCESS - voice data extraction OK")
