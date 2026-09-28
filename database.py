from sqlalchemy import create_engine, Column, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

DATABASE_URL = "sqlite:///./weathergpt.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class IMDWeatherCache(Base):
    __tablename__ = "imd_weather"

    station_code = Column(String, primary_key=True, index=True)
    station_name = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    max_temp_c = Column(Float, nullable=True)
    min_temp_c = Column(Float, nullable=True)
    humidity_pct = Column(Float, nullable=True)
    forecast_desc = Column(String, nullable=True)
    last_updated = Column(DateTime, nullable=True)

Base.metadata.create_all(bind=engine)