from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Product


def list_products(session: Session):
    return session.query(Product).order_by(Product.sku).all()


def low_stock(session: Session, threshold: int = 5):
    return (
        session.query(Product)
        .filter(Product.reorder_level <= threshold)
        .order_by(Product.reorder_level)
        .all()
    )


# SEEDED BUG (MX-DB-003, query references a nonexistent column): neither the
# model nor the schema has "last_counted_at". Raw SQL bypasses the ORM, so
# nothing catches this until it runs.
def recently_counted(session: Session):
    return session.execute(
        text(
            "SELECT id, sku, name, last_counted_at "
            "FROM products "
            "ORDER BY last_counted_at DESC "
            "LIMIT 20"
        )
    ).all()


def product_totals(session: Session):
    return session.execute(
        text("SELECT supplier_id, COUNT(*) AS total FROM products GROUP BY supplier_id")
    ).all()
