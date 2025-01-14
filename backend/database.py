# database.py

from sqlalchemy import (
    create_engine, Column, Integer, Text, DateTime, String,
    LargeBinary, Float, Boolean, Date, ForeignKey
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

###############################################################################
# SQLAlchemy Setup
###############################################################################
Base = declarative_base()
engine = create_engine("sqlite:///chat_history.db", echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

###############################################################################
# ChatExchange & Document Tables
###############################################################################
class ChatExchange(Base):
    """
    Stores user <-> LLM interactions. Also supports storing images
    if user sent an image + prompt. The table includes:
      - user_message: The original text from the user
      - llm_response: The LLM’s final text
      - user_image_b64: If an image was provided, store its base64
      - image_title / image_description: If the LLM provided structured info
    """
    __tablename__ = "chat_exchanges"

    id = Column(Integer, primary_key=True, index=True)
    user_message = Column(Text, nullable=True)
    llm_response = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    # If user sent an image:
    user_image_b64 = Column(Text, nullable=True)
    image_title = Column(Text, nullable=True)
    image_description = Column(Text, nullable=True)


class Document(Base):
    """
    Example table for storing uploaded documents (like PDFs, images)
    as binary data plus extracted text content. Could also be used
    by the parse_block if we want the LLM to parse text in them.
    """
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)
    file_content = Column(LargeBinary)
    upload_time = Column(DateTime, default=datetime.utcnow)
    text_content = Column(Text, nullable=True)
    description = Column(Text, nullable=True)

###############################################################################
# Domain-Specific Tables (Fridge Items, Shopping List, Invoices, etc.)
###############################################################################
class FridgeItem(Base):
    """
    The 'fridge_items' table. Here is where we store items that
    the user has physically in their fridge. For example:
      - name='Milk', quantity=1.0, unit='liter', expiration_date=YYYY-MM-DD, category='dairy'
    The LLM will do an INSERT/UPDATE with 'sql_block' if the user requests to add or modify items.
    """
    __tablename__ = "fridge_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    quantity = Column(Float, default=1.0)
    unit = Column(String, default="unit")
    expiration_date = Column(Date, nullable=True)
    category = Column(String, nullable=True)


class ShoppingItem(Base):
    """
    The 'shopping_items' table for items on a shopping list.
    For example:
      - name='Tomatoes', desired_quantity=5, unit='units', purchased=False
    """
    __tablename__ = "shopping_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    desired_quantity = Column(Float, default=1.0)
    unit = Column(String, default="unit")
    purchased = Column(Boolean, default=False)


class Invoice(Base):
    """
    The 'invoices' table: one row per invoice/receipt. This table is
    'REQUIRE_USER' in table_permissions, meaning user must confirm writes
    (in your baby-step scenario we assume user_permission=True).
    Potential usage: 
      - parse_block => parse invoice text => produce structured line items
      - sql_block => do INSERT INTO invoices(...) plus invoice_items(...)
    """
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False)  # e.g. date of purchase
    total_amount = Column(Float, default=0.0)
    store_name = Column(String, nullable=True)

    # Relationship: invoice has many invoice_items
    items = relationship("InvoiceItem", back_populates="invoice")


class InvoiceItem(Base):
    """
    The line items for a given invoice, e.g. 
      - name='Chicken Breast', quantity=2.0, price_per_unit=5.0, invoice_id=?
    """
    __tablename__ = "invoice_items"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"))
    name = Column(String, nullable=False)
    quantity = Column(Float, default=1.0)
    price_per_unit = Column(Float, default=0.0)

    invoice = relationship("Invoice", back_populates="items")


class MonthlySpending(Base):
    """
    Example table for monthly spend tracking. 
    Another 'ALWAYS_DENY' for writes in baby step, so agent
    cannot do INSERT/UPDATE/DELETE on monthly_spendings.
    """
    __tablename__ = "monthly_spendings"

    id = Column(Integer, primary_key=True, index=True)
    year_month = Column(String, nullable=False)  # e.g. "2025-01"
    total_spent = Column(Float, default=0.0)

###############################################################################
# Create all tables once
###############################################################################
Base.metadata.create_all(bind=engine)

###############################################################################
# Table Permissions
###############################################################################
# We define which tables are ALWAYS_ALLOW, REQUIRE_USER, or ALWAYS_DENY for writes.
# This is used by the 'sql_block' to decide if an INSERT/UPDATE/DELETE is permitted.
table_permissions = {
    "chat_exchanges":    "ALWAYS_DENY",   # never allow writes from the LLM
    "documents":         "ALWAYS_DENY",   # same reason
    "fridge_items":      "ALWAYS_ALLOW",  # can always INSERT/UPDATE
    "shopping_items":    "ALWAYS_ALLOW",  # can always INSERT/UPDATE
    "invoices":          "REQUIRE_USER",  # user_permission=True for now
    "invoice_items":     "REQUIRE_USER",  # user_permission=True for now
    "monthly_spendings": "ALWAYS_DENY"    # denies writes
}
