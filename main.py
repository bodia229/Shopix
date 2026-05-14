import os, json, re, uuid, threading
from dotenv import load_dotenv
load_dotenv()
import locales
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Request, Depends, Form, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import database, models, auth
database.Base.metadata.create_all(bind=database.engine)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
STRIPE_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUB = os.getenv("STRIPE_PUBLISHABLE_KEY", "")


# ── HELPERS ───────────────────────────────────────────────
def get_user(request: Request, db: Session):
    return auth.get_current_user(request.cookies.get("token"), db)


def get_session_id(request: Request, response: Response) -> str:
    sid = request.cookies.get("sid")
    if not sid:
        sid = uuid.uuid4().hex
    return sid


def cart_count(request: Request, db: Session) -> int:
    user = get_user(request, db)
    sid  = request.cookies.get("sid", "")
    if user:
        return db.query(models.CartItem).filter(models.CartItem.user_id == user.id).count()
    return db.query(models.CartItem).filter(models.CartItem.session_id == sid).count()


def get_lang(request: Request) -> str:
    lang = request.query_params.get("lang") or request.cookies.get("lang", "cs")
    return lang if lang in locales.LANGS else "cs"


def base_ctx(request: Request, db: Session, page: str = "") -> dict:
    user = get_user(request, db)
    categories = db.query(models.Category).order_by(models.Category.sort_order).all()
    lang = get_lang(request)
    return {
        "user": user,
        "categories": categories,
        "cart_count": cart_count(request, db),
        "current_page": page,
        "BASE_URL": BASE_URL,
        "STRIPE_PUB": STRIPE_PUB,
        "t": locales.T[lang],
        "lang": lang,
        "LANGS": locales.LANGS,
    }


def require_admin(user):
    if not user or not user.is_admin:
        raise HTTPException(403, "Forbidden")
    return user


def make_slug(name: str, db: Session, model=None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        slug = "item"
    if model:
        base, n = slug, 1
        while db.query(model).filter(model.slug == slug).first():
            slug = f"{base}-{n}"; n += 1
    return slug


def _migrate():
    is_pg = not str(database.DATABASE_URL).startswith("sqlite")
    stmts = []
    if is_pg:
        stmts = [
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_featured BOOLEAN DEFAULT FALSE",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS rating FLOAT DEFAULT 0",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS reviews_count INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(30)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS address TEXT",
        ]
    else:
        try:
            from sqlalchemy import text
            with database.engine.connect() as conn:
                for col in [("products","is_featured","INTEGER DEFAULT 0"),
                            ("products","rating","REAL DEFAULT 0"),
                            ("products","reviews_count","INTEGER DEFAULT 0"),
                            ("users","phone","TEXT"),("users","address","TEXT")]:
                    try:
                        conn.execute(text(f"ALTER TABLE {col[0]} ADD COLUMN {col[1]} {col[2]}"))
                        conn.commit()
                    except Exception:
                        pass
        except Exception:
            pass
        return
    if stmts:
        from sqlalchemy import text
        with database.engine.connect() as conn:
            for s in stmts:
                try:
                    conn.execute(text(s)); conn.commit()
                except Exception:
                    pass


def _seed(db: Session):
    if db.query(models.Category).count():
        return
    cats = [
        ("Смартфони", "smartphones", "📱", 1),
        ("Ноутбуки", "laptops", "💻", 2),
        ("Навушники", "headphones", "🎧", 3),
        ("Планшети", "tablets", "📲", 4),
        ("Розумний дім", "smart-home", "🏠", 5),
        ("Аксесуари", "accessories", "🔌", 6),
        ("Ігри та геймінг", "gaming", "🎮", 7),
        ("Фото та відео", "photo-video", "📷", 8),
    ]
    for name, slug, icon, order in cats:
        db.add(models.Category(name=name, slug=slug, icon=icon, sort_order=order))
    db.commit()


threading.Thread(target=lambda: (
    _migrate(),
    (lambda db: (_seed(db), db.close()))(database.SessionLocal())
), daemon=True).start()


# ── HOME ──────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(database.get_db)):
    ctx = base_ctx(request, db, "home")
    ctx["featured"] = db.query(models.Product).filter(
        models.Product.is_active == True,
        models.Product.is_featured == True
    ).limit(8).all()
    ctx["new_arrivals"] = db.query(models.Product).filter(
        models.Product.is_active == True
    ).order_by(models.Product.id.desc()).limit(8).all()
    return templates.TemplateResponse(request=request, name="index.html", context=ctx)


# ── CATALOG ───────────────────────────────────────────────
@app.get("/catalog", response_class=HTMLResponse)
async def catalog(
    request: Request,
    category: str = "",
    q: str = "",
    min_price: float = 0,
    max_price: float = 999999,
    brand: str = "",
    sort: str = "newest",
    page: int = 1,
    db: Session = Depends(database.get_db),
):
    ctx = base_ctx(request, db, "catalog")
    query = db.query(models.Product).filter(models.Product.is_active == True)

    if category:
        cat = db.query(models.Category).filter(models.Category.slug == category).first()
        if cat:
            query = query.filter(models.Product.category_id == cat.id)
            ctx["active_category"] = cat
    if q:
        query = query.filter(models.Product.name.ilike(f"%{q}%"))
    if min_price:
        query = query.filter(models.Product.price >= min_price)
    if max_price < 999999:
        query = query.filter(models.Product.price <= max_price)
    if brand:
        query = query.filter(models.Product.brand.ilike(f"%{brand}%"))

    if sort == "price_asc":
        query = query.order_by(models.Product.price.asc())
    elif sort == "price_desc":
        query = query.order_by(models.Product.price.desc())
    elif sort == "popular":
        query = query.order_by(models.Product.reviews_count.desc())
    else:
        query = query.order_by(models.Product.id.desc())

    per_page = 20
    total = query.count()
    products = query.offset((page - 1) * per_page).limit(per_page).all()

    brands = [r[0] for r in db.query(models.Product.brand).filter(
        models.Product.is_active == True, models.Product.brand != ""
    ).distinct().all()]

    ctx.update({
        "products": products, "total": total, "page": page,
        "pages": (total + per_page - 1) // per_page,
        "q": q, "category": category, "sort": sort,
        "min_price": min_price, "max_price": max_price,
        "brand": brand, "brands": brands,
    })
    return templates.TemplateResponse(request=request, name="catalog.html", context=ctx)


# ── PRODUCT ───────────────────────────────────────────────
@app.get("/product/{slug}", response_class=HTMLResponse)
async def product_page(slug: str, request: Request, db: Session = Depends(database.get_db)):
    ctx = base_ctx(request, db)
    product = db.query(models.Product).filter(
        models.Product.slug == slug, models.Product.is_active == True
    ).first()
    if not product:
        raise HTTPException(404)
    cat = db.query(models.Category).filter(models.Category.id == product.category_id).first()
    reviews = db.query(models.Review).filter(
        models.Review.product_id == product.id
    ).order_by(models.Review.id.desc()).limit(20).all()
    related = db.query(models.Product).filter(
        models.Product.category_id == product.category_id,
        models.Product.id != product.id,
        models.Product.is_active == True,
    ).limit(4).all()
    specs = {}
    if product.specs:
        try:
            specs = json.loads(product.specs)
        except Exception:
            pass
    images = []
    if product.images:
        try:
            images = json.loads(product.images)
        except Exception:
            pass
    ctx.update({
        "product": product, "category": cat,
        "reviews": reviews, "related": related,
        "specs": specs, "images": images,
    })
    return templates.TemplateResponse(request=request, name="product.html", context=ctx)


# ── CART ──────────────────────────────────────────────────
@app.get("/cart", response_class=HTMLResponse)
async def cart_page(request: Request, db: Session = Depends(database.get_db)):
    ctx = base_ctx(request, db, "cart")
    user = ctx["user"]
    sid  = request.cookies.get("sid", "")
    if user:
        items = db.query(models.CartItem).filter(models.CartItem.user_id == user.id).all()
    else:
        items = db.query(models.CartItem).filter(models.CartItem.session_id == sid).all()
    cart = []
    total = 0.0
    for item in items:
        p = db.query(models.Product).filter(models.Product.id == item.product_id).first()
        if p:
            subtotal = p.price * item.quantity
            total += subtotal
            cart.append({"item": item, "product": p, "subtotal": subtotal})
    ctx["cart"] = cart
    ctx["total"] = total
    return templates.TemplateResponse(request=request, name="cart.html", context=ctx)


@app.post("/cart/add")
async def cart_add(
    request: Request,
    product_id: int = Form(...),
    quantity: int = Form(1),
    db: Session = Depends(database.get_db),
):
    user = get_user(request, db)
    sid  = request.cookies.get("sid", uuid.uuid4().hex)
    product = db.query(models.Product).filter(
        models.Product.id == product_id, models.Product.is_active == True
    ).first()
    if not product:
        return JSONResponse({"ok": False}, status_code=404)

    if user:
        existing = db.query(models.CartItem).filter(
            models.CartItem.user_id == user.id,
            models.CartItem.product_id == product_id
        ).first()
        if existing:
            existing.quantity += quantity
        else:
            db.add(models.CartItem(user_id=user.id, product_id=product_id, quantity=quantity))
    else:
        existing = db.query(models.CartItem).filter(
            models.CartItem.session_id == sid,
            models.CartItem.product_id == product_id
        ).first()
        if existing:
            existing.quantity += quantity
        else:
            db.add(models.CartItem(session_id=sid, product_id=product_id, quantity=quantity))
    db.commit()
    resp = JSONResponse({"ok": True})
    resp.set_cookie("sid", sid, max_age=60*60*24*30, httponly=True)
    return resp


@app.post("/cart/update")
async def cart_update(
    request: Request,
    item_id: int = Form(...),
    quantity: int = Form(...),
    db: Session = Depends(database.get_db),
):
    user = get_user(request, db)
    sid  = request.cookies.get("sid", "")
    item = db.query(models.CartItem).filter(models.CartItem.id == item_id).first()
    if not item:
        return JSONResponse({"ok": False})
    if user and item.user_id != user.id:
        return JSONResponse({"ok": False})
    if not user and item.session_id != sid:
        return JSONResponse({"ok": False})
    if quantity <= 0:
        db.delete(item)
    else:
        item.quantity = quantity
    db.commit()
    return JSONResponse({"ok": True})


@app.post("/cart/remove")
async def cart_remove(
    request: Request,
    item_id: int = Form(...),
    db: Session = Depends(database.get_db),
):
    user = get_user(request, db)
    sid  = request.cookies.get("sid", "")
    item = db.query(models.CartItem).filter(models.CartItem.id == item_id).first()
    if item:
        if (user and item.user_id == user.id) or (not user and item.session_id == sid):
            db.delete(item)
            db.commit()
    return RedirectResponse("/cart", 302)


# ── CHECKOUT ──────────────────────────────────────────────
@app.get("/checkout", response_class=HTMLResponse)
async def checkout_page(request: Request, db: Session = Depends(database.get_db)):
    ctx = base_ctx(request, db, "checkout")
    user = ctx["user"]
    sid  = request.cookies.get("sid", "")
    if user:
        items = db.query(models.CartItem).filter(models.CartItem.user_id == user.id).all()
    else:
        items = db.query(models.CartItem).filter(models.CartItem.session_id == sid).all()
    if not items:
        return RedirectResponse("/cart", 302)
    cart = []
    total = 0.0
    for item in items:
        p = db.query(models.Product).filter(models.Product.id == item.product_id).first()
        if p:
            subtotal = p.price * item.quantity
            total += subtotal
            cart.append({"item": item, "product": p, "subtotal": subtotal})
    ctx["cart"] = cart
    ctx["total"] = total
    return templates.TemplateResponse(request=request, name="checkout.html", context=ctx)


@app.post("/checkout/place")
async def checkout_place(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    address: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(database.get_db),
):
    user = get_user(request, db)
    sid  = request.cookies.get("sid", "")
    if user:
        items = db.query(models.CartItem).filter(models.CartItem.user_id == user.id).all()
    else:
        items = db.query(models.CartItem).filter(models.CartItem.session_id == sid).all()
    if not items:
        return RedirectResponse("/cart", 302)

    total = 0.0
    order_items_data = []
    for item in items:
        p = db.query(models.Product).filter(models.Product.id == item.product_id).first()
        if p:
            total += p.price * item.quantity
            order_items_data.append((p, item.quantity))

    order = models.Order(
        user_id=user.id if user else None,
        name=name, email=email, phone=phone,
        address=address, notes=notes, total=total,
        status="pending", payment_status="unpaid",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    for p, qty in order_items_data:
        db.add(models.OrderItem(
            order_id=order.id, product_id=p.id,
            name=p.name, price=p.price, quantity=qty, image=p.image
        ))

    for item in items:
        db.delete(item)
    db.commit()

    return RedirectResponse(f"/order/{order.id}/success", 302)


@app.get("/order/{order_id}/success", response_class=HTMLResponse)
async def order_success(order_id: int, request: Request, db: Session = Depends(database.get_db)):
    ctx = base_ctx(request, db)
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(404)
    order_items = db.query(models.OrderItem).filter(models.OrderItem.order_id == order_id).all()
    ctx["order"] = order
    ctx["order_items"] = order_items
    return templates.TemplateResponse(request=request, name="order_success.html", context=ctx)


# ── AUTH ──────────────────────────────────────────────────
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: Session = Depends(database.get_db)):
    ctx = base_ctx(request, db, "login")
    if ctx["user"]:
        return RedirectResponse("/profile", 302)
    return templates.TemplateResponse(request=request, name="login.html", context=ctx)


@app.post("/login")
async def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next_url: str = Form(""),
    db: Session = Depends(database.get_db),
):
    ctx = base_ctx(request, db, "login")
    user = db.query(models.User).filter(models.User.email == email.lower()).first()
    if not user or not auth.verify_password(password, user.hashed_password):
        ctx["error"] = "Невірний email або пароль"
        return templates.TemplateResponse(request=request, name="login.html", context=ctx)
    landing = "/admin" if user.is_admin else (next_url or "/profile")
    resp = RedirectResponse(landing, 302)
    resp.set_cookie("token", auth.create_token(user.id), httponly=True, max_age=60*60*24*30)
    return resp


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, db: Session = Depends(database.get_db)):
    ctx = base_ctx(request, db, "register")
    if ctx["user"]:
        return RedirectResponse("/profile", 302)
    return templates.TemplateResponse(request=request, name="register.html", context=ctx)


@app.post("/register")
async def register_post(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(database.get_db),
):
    ctx = base_ctx(request, db, "register")
    if db.query(models.User).filter(models.User.email == email.lower()).first():
        ctx["error"] = "Цей email вже зареєстрований"
        return templates.TemplateResponse(request=request, name="register.html", context=ctx)
    if len(password) < 6:
        ctx["error"] = "Пароль мінімум 6 символів"
        return templates.TemplateResponse(request=request, name="register.html", context=ctx)
    user = models.User(
        name=name.strip(),
        email=email.lower().strip(),
        hashed_password=auth.hash_password(password),
    )
    if db.query(models.User).count() == 0:
        user.is_admin = True
    db.add(user)
    db.commit()
    db.refresh(user)
    resp = RedirectResponse("/profile", 302)
    resp.set_cookie("token", auth.create_token(user.id), httponly=True, max_age=60*60*24*30)
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/", 302)
    resp.delete_cookie("token")
    return resp


# ── PROFILE ───────────────────────────────────────────────
@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, db: Session = Depends(database.get_db)):
    ctx = base_ctx(request, db, "profile")
    user = ctx["user"]
    if not user:
        return RedirectResponse("/login?next=/profile", 302)
    orders = db.query(models.Order).filter(
        models.Order.user_id == user.id
    ).order_by(models.Order.id.desc()).all()
    for o in orders:
        o.items = db.query(models.OrderItem).filter(models.OrderItem.order_id == o.id).all()
    ctx["orders"] = orders
    return templates.TemplateResponse(request=request, name="profile.html", context=ctx)


# ── ADMIN ─────────────────────────────────────────────────
@app.get("/admin", response_class=HTMLResponse)
async def admin_dash(request: Request, db: Session = Depends(database.get_db)):
    ctx = base_ctx(request, db)
    require_admin(ctx["user"])
    ctx["active"] = "dash"
    ctx["total_products"] = db.query(models.Product).count()
    ctx["total_orders"]   = db.query(models.Order).count()
    ctx["total_users"]    = db.query(models.User).count()
    ctx["revenue"] = sum(o.total for o in db.query(models.Order).filter(
        models.Order.payment_status == "paid").all()) or 0
    ctx["recent_orders"] = db.query(models.Order).order_by(
        models.Order.id.desc()).limit(10).all()
    return templates.TemplateResponse(request=request, name="admin/dashboard.html", context=ctx)


# ── ADMIN PRODUCTS ─────────────────────────────────────────
@app.get("/admin/products", response_class=HTMLResponse)
async def admin_products(request: Request, db: Session = Depends(database.get_db)):
    ctx = base_ctx(request, db)
    require_admin(ctx["user"])
    ctx["active"] = "products"
    ctx["products"] = db.query(models.Product).order_by(models.Product.id.desc()).all()
    ctx["categories"] = db.query(models.Category).order_by(models.Category.sort_order).all()
    return templates.TemplateResponse(request=request, name="admin/products.html", context=ctx)


@app.get("/admin/products/new", response_class=HTMLResponse)
async def admin_product_new_get(request: Request, db: Session = Depends(database.get_db)):
    ctx = base_ctx(request, db)
    require_admin(ctx["user"])
    ctx["active"] = "products"
    ctx["product"] = None
    ctx["categories"] = db.query(models.Category).order_by(models.Category.sort_order).all()
    return templates.TemplateResponse(request=request, name="admin/product_form.html", context=ctx)


@app.post("/admin/products/new")
async def admin_product_new_post(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    price: float = Form(...),
    old_price: Optional[float] = Form(None),
    category_id: Optional[int] = Form(None),
    brand: str = Form(""),
    sku: str = Form(""),
    stock: int = Form(0),
    image: str = Form(""),
    specs: str = Form(""),
    is_active: bool = Form(True),
    is_featured: bool = Form(False),
    db: Session = Depends(database.get_db),
):
    ctx = base_ctx(request, db)
    require_admin(ctx["user"])
    slug = make_slug(name, db, models.Product)
    p = models.Product(
        name=name, slug=slug, description=description,
        price=price, old_price=old_price,
        category_id=category_id if category_id else None,
        brand=brand, sku=sku, stock=stock, image=image,
        specs=specs, is_active=is_active, is_featured=is_featured,
    )
    db.add(p)
    db.commit()
    return RedirectResponse("/admin/products", 302)


@app.get("/admin/products/edit/{product_id}", response_class=HTMLResponse)
async def admin_product_edit_get(product_id: int, request: Request, db: Session = Depends(database.get_db)):
    ctx = base_ctx(request, db)
    require_admin(ctx["user"])
    ctx["active"] = "products"
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(404)
    ctx["product"] = product
    ctx["categories"] = db.query(models.Category).order_by(models.Category.sort_order).all()
    return templates.TemplateResponse(request=request, name="admin/product_form.html", context=ctx)


@app.post("/admin/products/edit/{product_id}")
async def admin_product_edit_post(
    product_id: int, request: Request,
    name: str = Form(...),
    description: str = Form(""),
    price: float = Form(...),
    old_price: Optional[float] = Form(None),
    category_id: Optional[int] = Form(None),
    brand: str = Form(""),
    sku: str = Form(""),
    stock: int = Form(0),
    image: str = Form(""),
    specs: str = Form(""),
    is_active: bool = Form(True),
    is_featured: bool = Form(False),
    db: Session = Depends(database.get_db),
):
    ctx = base_ctx(request, db)
    require_admin(ctx["user"])
    p = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not p:
        raise HTTPException(404)
    p.name = name; p.description = description; p.price = price
    p.old_price = old_price; p.category_id = category_id if category_id else None
    p.brand = brand; p.sku = sku; p.stock = stock; p.image = image
    p.specs = specs; p.is_active = is_active; p.is_featured = is_featured
    db.commit()
    return RedirectResponse("/admin/products", 302)


@app.post("/admin/products/delete/{product_id}")
async def admin_product_delete(product_id: int, request: Request, db: Session = Depends(database.get_db)):
    ctx = base_ctx(request, db)
    require_admin(ctx["user"])
    p = db.query(models.Product).filter(models.Product.id == product_id).first()
    if p:
        db.delete(p); db.commit()
    return RedirectResponse("/admin/products", 302)


# ── ADMIN ORDERS ──────────────────────────────────────────
@app.get("/admin/orders", response_class=HTMLResponse)
async def admin_orders(request: Request, db: Session = Depends(database.get_db)):
    ctx = base_ctx(request, db)
    require_admin(ctx["user"])
    ctx["active"] = "orders"
    orders = db.query(models.Order).order_by(models.Order.id.desc()).all()
    for o in orders:
        o.items = db.query(models.OrderItem).filter(models.OrderItem.order_id == o.id).all()
    ctx["orders"] = orders
    return templates.TemplateResponse(request=request, name="admin/orders.html", context=ctx)


@app.post("/admin/orders/{order_id}/status")
async def admin_order_status(
    order_id: int, request: Request,
    status: str = Form(...),
    db: Session = Depends(database.get_db),
):
    ctx = base_ctx(request, db)
    require_admin(ctx["user"])
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if order:
        order.status = status
        db.commit()
    return RedirectResponse("/admin/orders", 302)


# ── ADMIN CATEGORIES ──────────────────────────────────────
@app.get("/admin/categories", response_class=HTMLResponse)
async def admin_categories(request: Request, db: Session = Depends(database.get_db)):
    ctx = base_ctx(request, db)
    require_admin(ctx["user"])
    ctx["active"] = "categories"
    ctx["categories"] = db.query(models.Category).order_by(models.Category.sort_order).all()
    return templates.TemplateResponse(request=request, name="admin/categories.html", context=ctx)


@app.post("/admin/categories/add")
async def admin_category_add(
    request: Request,
    name: str = Form(...),
    icon: str = Form("📦"),
    sort_order: int = Form(0),
    db: Session = Depends(database.get_db),
):
    ctx = base_ctx(request, db)
    require_admin(ctx["user"])
    slug = make_slug(name, db, models.Category)
    db.add(models.Category(name=name, slug=slug, icon=icon, sort_order=sort_order))
    db.commit()
    return RedirectResponse("/admin/categories", 302)


@app.post("/admin/categories/delete/{cat_id}")
async def admin_category_delete(cat_id: int, request: Request, db: Session = Depends(database.get_db)):
    ctx = base_ctx(request, db)
    require_admin(ctx["user"])
    cat = db.query(models.Category).filter(models.Category.id == cat_id).first()
    if cat:
        db.delete(cat); db.commit()
    return RedirectResponse("/admin/categories", 302)


# ── ADMIN USERS ───────────────────────────────────────────
@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request, db: Session = Depends(database.get_db)):
    ctx = base_ctx(request, db)
    require_admin(ctx["user"])
    ctx["active"] = "users"
    ctx["users"] = db.query(models.User).order_by(models.User.id.desc()).all()
    return templates.TemplateResponse(request=request, name="admin/users.html", context=ctx)


# ── COMPARE ───────────────────────────────────────────────
@app.get("/compare", response_class=HTMLResponse)
async def compare_page(request: Request, ids: str = "", db: Session = Depends(database.get_db)):
    ctx = base_ctx(request, db, "compare")
    if not ids:
        return RedirectResponse("/catalog", 302)
    id_list = []
    for i in ids.split(","):
        try:
            id_list.append(int(i.strip()))
        except Exception:
            pass
    products = db.query(models.Product).filter(models.Product.id.in_(id_list)).all()
    if not products:
        return RedirectResponse("/catalog", 302)
    all_spec_keys: list[str] = []
    seen: set[str] = set()
    specs_map: dict[int, dict] = {}
    for p in products:
        s: dict = {}
        if p.specs:
            try:
                s = json.loads(p.specs)
            except Exception:
                pass
        specs_map[p.id] = s
        for k in s:
            if k not in seen:
                seen.add(k)
                all_spec_keys.append(k)
    ctx["products"] = products
    ctx["spec_keys"] = all_spec_keys
    ctx["specs_map"] = specs_map
    return templates.TemplateResponse(request=request, name="compare.html", context=ctx)


# ── SET LANGUAGE ───────────────────────────────────────────
@app.get("/set-lang/{lang}")
async def set_lang(lang: str, request: Request):
    back = request.headers.get("referer", "/")
    if lang not in locales.LANGS:
        lang = "uk"
    resp = RedirectResponse(back, 302)
    resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, httponly=False)
    return resp


# ── REVIEW ────────────────────────────────────────────────
@app.post("/product/{product_id}/review")
async def add_review(
    product_id: int, request: Request,
    name: str = Form(...),
    rating: int = Form(5),
    text: str = Form(...),
    db: Session = Depends(database.get_db),
):
    user = get_user(request, db)
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(404)
    db.add(models.Review(
        product_id=product_id,
        user_id=user.id if user else None,
        name=name.strip() or (user.name if user else "Анонім"),
        rating=max(1, min(5, rating)),
        text=text.strip(),
    ))
    reviews = db.query(models.Review).filter(models.Review.product_id == product_id).all()
    if reviews:
        product.rating = round(sum(r.rating for r in reviews) / len(reviews), 1)
        product.reviews_count = len(reviews)
    db.commit()
    return RedirectResponse(f"/product/{product.slug}#reviews", 302)
