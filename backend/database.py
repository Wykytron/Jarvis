# backend/database.py

from sqlalchemy import create_engine, Column, Integer, Text, DateTime, String, LargeBinary
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
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

    # For re-displaying images in the chat
    # We'll store base64 data if user sends an image
    user_image_b64 = Column(Text, nullable=True)
    # If the assistant returns an image (rare?), we could also do assistant_image_b64

class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)
    file_content = Column(LargeBinary)  # store raw bytes
    upload_time = Column(DateTime, default=datetime.utcnow)
    text_content = Column(Text, nullable=True)
    description = Column(Text, nullable=True)

Base.metadata.create_all(bind=engine)
