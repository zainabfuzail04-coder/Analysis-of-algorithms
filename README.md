# Hotel Management System (Flask)

Web Engineering CSE601330 - Flask project. 41 related SQLAlchemy tables, full CRUD, server-side validation, sessions + cookies, soft delete, search/filter/pagination.

## Setup
```bash
python -m venv venv
venv\Scripts\activate          # Windows   (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
python seed.py                 # demo data (admin / staff / guest logins neeche)
python app.py                  # http://127.0.0.1:5000
```
Env vars (optional): `SECRET_KEY` (deploy se pehle zaroor), `PAYMENT_GATEWAY` (default `sandbox`), `MAIL_SERVER/MAIL_PORT/MAIL_USERNAME/MAIL_PASSWORD/MAIL_FROM` (email), `FLASK_DEBUG=0`, `DATABASE_URL` (default SQLite `hotel.db`; MySQL bhi chalta hai, e.g. `mysql+pymysql://user:pass@localhost/hotel`).

## Features
- Login with email, Register (hashed passwords, session, `last_user` cookie, safe `next` redirect)
- 41 tables: People, Rooms, Bookings, Billing, Services, Operations
- Har table mein: id, status (active/deactive), is_deleted, created_at/by, updated_at/by, deleted_at/by
- CRUD + soft delete (Admin only), status toggle, search, status filter, pagination
- Business rules: check-out > check-in, room double-booking check, rating 1-5, FK/unique/type validation
- Post-Redirect-Get + flash messages; AuditLog table
- Dashboard (counts + revenue)
- Guest portal: sign up, search rooms by dates/type/price, book + instant confirmation, invoice, edit dates, cancel (refund rule), demo payment, profile edit
- Secure checkout: card validation (Luhn, expiry, CVV), approve/decline, transaction id, partial or full payment, printable receipt, one-time form token (double-click = double charge nahi). Card number/CVV kabhi save nahi hote (sirf brand + last4)
- Refunds: cancel (2+ din pehle = full refund) aur booking sasti karne par farq automatic wapis, negative Payment row ke zariye
- Confirmation: flash message + in-app Notification + email (SMTP set ho to real, warna terminal mein print)
- Front desk (`/staff/front-desk`): check-in, cash/card collect, check-out (balance clear hona zaroori), room status + housekeeping task automatic
- Security: CSRF origin check + SameSite cookie, safe `next` redirect, deleted/deactive user ka session foran khatam
- Demo logins after seed: admin@hotel.com / admin123, staff@hotel.com / staff123, guest@hotel.com / guest123

## Payment gateway
Default `sandbox` = test mode (asli paisa move nahi hota). Test cards: `4242 4242 4242 4242` approve, `4000 0000 0000 0002` decline, `4000 0000 0000 9995` insufficient funds.
Asli paisa ke liye gateway merchant account chahiye (Stripe, Safepay, PayFast, JazzCash...). `payments.py` mein bas naya class banao jis mein `charge()` / `refund()` ho aur `GATEWAYS` mein add karo; baqi poora flow wahi rehta hai.

## Structure
`app.py` factory (+ auto column migration) | `models.py` 41 models | `views.py` routes | `payments.py` card + gateway | `mailer.py` email | `seed.py` | `templates/` (naye: `checkout.html`, `receipt.html`, `front_desk.html`)
