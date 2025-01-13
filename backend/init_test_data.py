# Quick script: "init_test_data.py" or similar
# in your project root or "backend" folder:
import datetime
from database import engine, Base, SessionLocal
from database import FridgeItem, ShoppingItem, Invoice, InvoiceItem

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

db = SessionLocal()

# 1) Fridge Items
item1 = FridgeItem(name="Milk", quantity=1, unit="liters", expiration_date=datetime.date(2025, 2, 1), category="dairy")
item2 = FridgeItem(name="Eggs", quantity=12, unit="unit", expiration_date=datetime.date(2025, 1, 20), category="dairy")
item3 = FridgeItem(name="Spinach", quantity=1, unit="bag", expiration_date=datetime.date(2025, 1, 18), category="vegetables")
db.add_all([item1, item2, item3])

# 2) Shopping List
shop1 = ShoppingItem(name="Cheese", desired_quantity=1, unit="pack", purchased=False)
shop2 = ShoppingItem(name="Tomatoes", desired_quantity=5, unit="unit", purchased=False)
shop3 = ShoppingItem(name="Chicken Breast", desired_quantity=2, unit="kg", purchased=False)
db.add_all([shop1, shop2, shop3])

# 3) Invoices
inv1 = Invoice(date=datetime.date(2025,1,10), total_amount=23.50, store_name="SuperMart")
inv1_item1 = InvoiceItem(name="Milk", quantity=2, price_per_unit=1.20)
inv1_item2 = InvoiceItem(name="Butter", quantity=1, price_per_unit=2.50)
inv1.items = [inv1_item1, inv1_item2]

inv2 = Invoice(date=datetime.date(2025,1,15), total_amount=45.00, store_name="GroceryTown")
inv2_item1 = InvoiceItem(name="Chicken Breast", quantity=2, price_per_unit=5.00)
inv2_item2 = InvoiceItem(name="Eggs", quantity=12, price_per_unit=0.15)
inv2.items = [inv2_item1, inv2_item2]

db.add(inv1)
db.add(inv2)

db.commit()
db.close()
print("Test data inserted successfully!")