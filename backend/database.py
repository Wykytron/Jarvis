# database.py
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

Base.metadata.create_all(bind=engine)
