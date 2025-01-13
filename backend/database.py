# database.py

from sqlalchemy import (
    create_engine, Column, Integer, Text, DateTime, String,
    LargeBinary, Float, Boolean, Date, ForeignKey
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

Base = declarative_base()
engine = create_engine("sqlite:///chat_history.db", echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class ChatExchange(Base):
    __tablename__ = "chat_exchanges"

    id = Column(Integer, primary_key=True, index=True)
    user_message = Column(Text, nullable=True)
    llm_response = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    # For re-displaying images
    user_image_b64 = Column(Text, nullable=True)

    # The LLM's structured data if it was an image:
    image_title = Column(Text, nullable=True)
    image_description = Column(Text, nullable=True)


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)
    file_content = Column(LargeBinary)
    upload_time = Column(DateTime, default=datetime.utcnow)
    text_content = Column(Text, nullable=True)
    description = Column(Text, nullable=True)


# 1) Fridge items
class FridgeItem(Base):
    __tablename__ = "fridge_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    quantity = Column(Float, default=1.0)     # e.g. "2.0" for 2 units
    unit = Column(String, default="unit")     # e.g. "unit", "g", "ml", etc.
    expiration_date = Column(Date, nullable=True)
    category = Column(String, nullable=True)  # e.g. "dairy", "veggies"

    # e.g. added_time = Column(DateTime, default=datetime.utcnow)
    # if you want to track when it was put in the fridge


# 2) Shopping List
class ShoppingItem(Base):
    __tablename__ = "shopping_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    desired_quantity = Column(Float, default=1.0)
    unit = Column(String, default="unit")
    purchased = Column(Boolean, default=False)
    # optional: "planned_date" or "target_store"


# 3) Invoice / InvoiceItem (one-to-many)
class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False)   # date of purchase
    total_amount = Column(Float, default=0.0)
    store_name = Column(String, nullable=True)
    # store other fields if you want, e.g. "payment_type", "notes" etc.

    items = relationship("InvoiceItem", back_populates="invoice")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"))
    name = Column(String, nullable=False)
    quantity = Column(Float, default=1.0)
    price_per_unit = Column(Float, default=0.0)

    invoice = relationship("Invoice", back_populates="items")


# 4) Additional table "spendings"
#    Could be derived from invoice data, or used for your custom logic.
class MonthlySpending(Base):
    __tablename__ = "monthly_spendings"

    id = Column(Integer, primary_key=True, index=True)
    year_month = Column(String, nullable=False)   # e.g. "2025-01"
    total_spent = Column(Float, default=0.0)


Base.metadata.create_all(bind=engine)
