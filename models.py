import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, DateTime
from database import Base


def gen_id():
    return uuid.uuid4().hex[:12]


class Region(Base):
    """
    One row per (country, region). Stands in for what would, in production,
    be live census, infrastructure-ministry, and public-finance datasets.
    """
    __tablename__ = "regions"

    id = Column(String, primary_key=True, default=gen_id)
    country_code = Column(String, index=True, nullable=False)   # IN, BR, RU, CN, ZA
    name = Column(String, nullable=False)
    poverty_index = Column(Float, nullable=False)      # 0-1, higher = more vulnerable
    infra_score = Column(Float, nullable=False)         # 0-1, higher = better existing infra
    investment_level = Column(Float, nullable=False)    # 0-1, higher = more public investment already allocated


class CitizenRequest(Base):
    """
    One row per citizen submission, after AI classification.
    """
    __tablename__ = "citizen_requests"

    id = Column(String, primary_key=True, default=gen_id)
    country_code = Column(String, index=True, nullable=False)
    region = Column(String, index=True, nullable=False)
    citizen_id = Column(String, index=True, nullable=False)   # anonymous client-generated id, for "my requests"
    channel = Column(String, nullable=False)                   # Text / web form, Voice, WhatsApp (simulated)

    original_text = Column(String, nullable=False)
    detected_language = Column(String, nullable=False)
    translated_text = Column(String, nullable=False)
    sector = Column(String, index=True, nullable=False)
    severity = Column(Integer, nullable=False)                 # 1-5, per the rubric in ai_client.py
    severity_reason = Column(String, nullable=True)
    summary = Column(String, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
