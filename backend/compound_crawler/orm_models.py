from sqlalchemy import Column, Integer, Numeric, TIMESTAMP, JSON, text
from sqlalchemy.dialects.postgresql import BYTEA
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class CompoundV3UserPosition(Base):
    __tablename__ = "compound_v3_user_positions"
    __table_args__ = {"schema": "loan"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(TIMESTAMP(timezone=True), nullable=False)
    user_address = Column(BYTEA, nullable=False)
    market = Column(BYTEA, nullable=False)
    collateral_value = Column(Numeric, nullable=False)
    borrow_value = Column(Numeric, nullable=False)
    health_factor = Column(Numeric, nullable=False)
    reserves = Column(JSON, nullable=False)
    created_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
