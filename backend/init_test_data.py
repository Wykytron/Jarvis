import datetime
from database import engine, Base, SessionLocal
from database import FridgeItem, ShoppingItem, Invoice, InvoiceItem, MonthlySpending

# Drop and recreate all tables:
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

db = SessionLocal()

# ---------------------------------------------------------------------------
# 1) FRIDGE ITEMS
# ---------------------------------------------------------------------------
item1 = FridgeItem(
    name="Milk",
    quantity=1,
    unit="liters",
    expiration_date=datetime.date(2025, 2, 1),
    category="dairy"
)
item2 = FridgeItem(
    name="Eggs",
    quantity=12,
    unit="unit",
    expiration_date=datetime.date(2025, 1, 20),
    category="dairy"
)
item3 = FridgeItem(
    name="Spinach",
    quantity=1,
    unit="bag",
    expiration_date=datetime.date(2025, 1, 18),
    category="vegetables"
)
item4 = FridgeItem(
    name="Orange Juice",
    quantity=2,
    unit="liters",
    expiration_date=datetime.date(2025, 2, 5),
    category="beverage"
)
item5 = FridgeItem(
    name="Yogurt",
    quantity=4,
    unit="cup",
    expiration_date=datetime.date(2025, 1, 25),
    category="dairy"
)

db.add_all([item1, item2, item3, item4, item5])

# ---------------------------------------------------------------------------
# 2) SHOPPING ITEMS (shopping_list)
# ---------------------------------------------------------------------------
shop1 = ShoppingItem(
    name="Cheese",
    desired_quantity=1,
    unit="pack",
    purchased=False
)
shop2 = ShoppingItem(
    name="Tomatoes",
    desired_quantity=5,
    unit="unit",
    purchased=False
)
shop3 = ShoppingItem(
    name="Chicken Breast",
    desired_quantity=2,
    unit="kg",
    purchased=False
)
shop4 = ShoppingItem(
    name="Broccoli",
    desired_quantity=1,
    unit="head",
    purchased=False
)
shop5 = ShoppingItem(
    name="Orange Juice",
    desired_quantity=2,
    unit="liters",
    purchased=True   # Suppose it was already purchased
)

db.add_all([shop1, shop2, shop3, shop4, shop5])

# ---------------------------------------------------------------------------
# 3) INVOICES
# ---------------------------------------------------------------------------
inv1 = Invoice(
    date=datetime.date(2025, 1, 10),
    total_amount=23.50,
    store_name="SuperMart"
)
inv1_item1 = InvoiceItem(
    name="Milk",
    quantity=2,
    price_per_unit=1.20
)
inv1_item2 = InvoiceItem(
    name="Butter",
    quantity=1,
    price_per_unit=2.50
)
inv1.items = [inv1_item1, inv1_item2]

inv2 = Invoice(
    date=datetime.date(2025, 1, 15),
    total_amount=45.00,
    store_name="GroceryTown"
)
inv2_item1 = InvoiceItem(
    name="Chicken Breast",
    quantity=2,
    price_per_unit=5.00
)
inv2_item2 = InvoiceItem(
    name="Eggs",
    quantity=12,
    price_per_unit=0.15
)
inv2.items = [inv2_item1, inv2_item2]

# Another invoice for extra coverage
inv3 = Invoice(
    date=datetime.date(2025, 1, 20),
    total_amount=30.75,
    store_name="CostCo"
)
inv3_item1 = InvoiceItem(
    name="Yogurt",
    quantity=6,
    price_per_unit=0.99
)
inv3_item2 = InvoiceItem(
    name="Spinach",
    quantity=2,
    price_per_unit=1.50
)
inv3.items = [inv3_item1, inv3_item2]

db.add(inv1)
db.add(inv2)
db.add(inv3)

# ---------------------------------------------------------------------------
# 4) MONTHLY SPENDINGS (always deny writes)
# ---------------------------------------------------------------------------
# This is mostly to see that attempts to insert here are always denied.
jan_spend = MonthlySpending(
    year_month="2025-01",
    total_spent=200.00
)
feb_spend = MonthlySpending(
    year_month="2025-02",
    total_spent=0.00
)

db.add(jan_spend)
db.add(feb_spend)

db.commit()
db.close()

print("Test data inserted successfully!")
