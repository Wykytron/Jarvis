from sqlalchemy import create_engine, Column, Integer, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

Base = declarative_base()
engine = create_engine("sqlite:///chat_history.db", echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class ChatExchange(Base):
    __tablename__ = "chat_exchanges"

    id = Column(Integer, primary_key=True, index=True)
    user_message = Column(Text)
    llm_response = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)
