from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, Float, Text, DateTime, ForeignKey
from database import Base


class User(Base):
    __tablename__ = "users"
    id              = Column(Integer, primary_key=True, index=True)
    name            = Column(String(120), nullable=False)
    email           = Column(String(200), unique=True, index=True, nullable=False)
    hashed_password = Column(String(200), nullable=False)
    phone           = Column(String(30), nullable=True)
    address         = Column(Text, nullable=True)
    is_admin        = Column(Boolean, default=False)
    created_at      = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Category(Base):
    __tablename__ = "categories"
    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(100), nullable=False)
    slug        = Column(String(120), unique=True, index=True)
    icon        = Column(String(10), default="📦")
    sort_order  = Column(Integer, default=0)


class Product(Base):
    __tablename__ = "products"
    id            = Column(Integer, primary_key=True, index=True)
    name          = Column(String(200), nullable=False)
    slug          = Column(String(220), unique=True, index=True)
    description   = Column(Text, default="")
    price         = Column(Float, nullable=False)
    old_price     = Column(Float, nullable=True)
    category_id   = Column(Integer, ForeignKey("categories.id"), nullable=True)
    brand         = Column(String(100), default="")
    sku           = Column(String(80), default="")
    stock         = Column(Integer, default=0)
    image         = Column(Text, default="")
    images        = Column(Text, default="")   # JSON list of extra images
    specs         = Column(Text, default="")   # JSON dict of specs
    is_active     = Column(Boolean, default=True)
    is_featured   = Column(Boolean, default=False)
    rating        = Column(Float, default=0.0)
    reviews_count = Column(Integer, default=0)
    created_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class CartItem(Base):
    __tablename__ = "cart_items"
    id         = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(64), index=True, nullable=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity   = Column(Integer, default=1)


class Order(Base):
    __tablename__ = "orders"
    id              = Column(Integer, primary_key=True, index=True)
    user_id         = Column(Integer, ForeignKey("users.id"), nullable=True)
    status          = Column(String(30), default="pending")   # pending/paid/shipped/delivered/cancelled
    total           = Column(Float, default=0.0)
    name            = Column(String(120), default="")
    email           = Column(String(200), default="")
    phone           = Column(String(30), default="")
    address         = Column(Text, default="")
    payment_method  = Column(String(30), default="stripe")
    payment_status  = Column(String(30), default="unpaid")
    stripe_session  = Column(String(200), nullable=True)
    notes           = Column(Text, default="")
    created_at      = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class OrderItem(Base):
    __tablename__ = "order_items"
    id         = Column(Integer, primary_key=True, index=True)
    order_id   = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    name       = Column(String(200), default="")
    price      = Column(Float, default=0.0)
    quantity   = Column(Integer, default=1)
    image      = Column(Text, default="")


class Review(Base):
    __tablename__ = "reviews"
    id         = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=True)
    name       = Column(String(120), default="")
    rating     = Column(Integer, default=5)
    text       = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
