from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    contact_email = Column(String(255), nullable=True)


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    sku = Column(String(64), nullable=False, unique=True)
    name = Column(String(200), nullable=False)

    # SEEDED BUG (MX-DB-001, model field missing from the database): the
    # 0002 migration never adds this column, so every SELECT fails with
    # "column products.warehouse_code does not exist".
    warehouse_code = Column(String(16), nullable=True)

    # SEEDED BUG (MX-DB-002, type mismatch): the migration creates this as
    # INTEGER, the model declares NUMERIC(10, 2). Prices silently truncate.
    unit_price = Column(Numeric(10, 2), nullable=False)

    reorder_level = Column(Integer, nullable=False, default=0)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # SEEDED BUG (MX-DB-004, missing foreign key): the migration creates
    # supplier_id as a plain integer with no REFERENCES clause and no index,
    # so orphaned rows are possible and the join is a sequential scan.
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    supplier = relationship("Supplier")
