# Southern Cross Auctions

## Project
Online auction platform for antiques/collectibles in Australia, built as a
university assignment. Code must be readable, PEP 8 compliant, commented,
and simple enough for students to explain line by line. Prefer clear code
over clever code.

## Stack (do not change without asking)
- Python 3.11+, Django 5.x, Django REST Framework
- MySQL 8 (InnoDB) via mysqlclient, database name: ict712_auction
- Celery + Redis broker, Celery Beat for periodic tasks
- Django templates + Bootstrap 5 (CDN) for the UI. No React, no WebSockets
- Email: console backend in development
- Payments: mocked "Pay now" step (optional Stripe test mode behind a setting)
- API: DRF with TokenAuthentication, docs via drf-spectacular at /api/docs/
- Secrets and DB credentials in .env via python-dotenv, never hardcoded

## Structure
- Project package: config/
- Apps: accounts, auctions (Category, Lot, Auction, Bid, Watchlist),
  payments, notifications, core (AuditLog, PlatformConfig, Dispute, reports)
- Business logic lives in services.py per app; views stay thin
- Web routes at normal URLs, REST API under /api/

## Roles
SELLER, BIDDER, MODERATOR, ADMIN, stored as a role field on a custom User
model (AUTH_USER_MODEL = "accounts.User", created before the first migration).

## Business rules
- Sellers cannot bid on their own lots
- Lots start as PENDING; only a Moderator can approve or reject
- Moderators may edit category/description but never prices
- Approving a lot creates its Auction
- First bid must be >= starting price; later bids must be >= current highest
  bid x (1 + increment%), increment default 5% (PlatformConfig)
- Bids are placed inside transaction.atomic() with select_for_update() on the
  Auction row to prevent race conditions
- Anti-sniping: a bid in the last 2 minutes extends end_time by 2 minutes,
  up to a configurable maximum number of extensions
- Bidders cannot retract bids; only Moderators can withdraw one (audit logged)
- At close: highest bid >= reserve -> SOLD and a Payment is created;
  otherwise NOT_SOLD
- Unpaid payments expire after 48 hours -> sale becomes NOT_SOLD
- A Seller cannot cancel an auction once it has bids; only Admin can
- Payment amounts show GST (10%) and platform commission (PlatformConfig)
- Every state-changing action writes an AuditLog entry

## Working rules
- Only implement the phase I ask for; do not build ahead
- After each phase: run makemigrations, migrate and python manage.py test,
  then summarise the files changed and how to test it manually
- Explain any non-obvious code in comments
