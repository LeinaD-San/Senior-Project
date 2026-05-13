import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

# ======================================================
# Database Configuration
# ======================================================
# Loads DATABASE_URL from the .env file. If it is missing, the app falls back to
# the local Postgres connection used during development.

load_dotenv()

URL_DATABASE = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5433/travelagent"
)

# ======================================================
# SQLAlchemy Engine, Session, and Base Model
# ======================================================
# engine manages the database connection.
# SessionLocal creates a database session for each backend request.
# Base is inherited by all SQLAlchemy models in models.py.
engine = create_engine(URL_DATABASE, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

