import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

load_dotenv()

URL_DATABASE = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5433/travelagent"
)

engine = create_engine(URL_DATABASE, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

