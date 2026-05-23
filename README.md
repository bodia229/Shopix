# Shopix

E-commerce platform with product catalog, cart, orders, and Stripe checkout, built with FastAPI.

## Tech Stack

- **Backend**: Python, FastAPI, SQLAlchemy, SQLite
- **Auth**: JWT (cookies), bcrypt
- **Payments**: Stripe
- **i18n**: Multi-language locales (`locales.py`)

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your credentials
uvicorn main:app --reload
```

Or double-click `start.bat` on Windows.

Open [http://localhost:8000](http://localhost:8000)

## Environment Variables

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | JWT signing key |
| `STRIPE_SECRET_KEY` | Stripe secret key |
| `STRIPE_PUBLISHABLE_KEY` | Stripe public key |
| `BASE_URL` | Public URL of the app |
