"""Routes: auth, dashboard, aur saari 41 tables ke liye generic CRUD (search + filter + soft delete)."""
import hmac
import secrets
from datetime import datetime, date
from functools import wraps
from urllib.parse import urlparse
from flask import (Blueprint, render_template, request, redirect, url_for,
                   session, flash, abort, make_response)
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash
from models import (db, MODELS, User, Role, Booking, BookingRoom, Room, Guest, Payment,
                    Feedback, AuditLog, RoomType, Invoice, InvoiceItem, Tax, Coupon,
                    Cancellation, PaymentMethod, Notification, CheckIn, CheckOut,
                    HousekeepingTask, Staff)
from payments import get_gateway, validate_card, money
from mailer import send_email

bp = Blueprint("main", __name__)

SYSTEM = {"id", "status", "is_deleted", "created_at", "created_by",
          "updated_at", "updated_by", "deleted_at", "deleted_by"}
HIDDEN = SYSTEM | {"password_hash"}
CHOICES = {
    "room_status": ["available", "occupied", "maintenance"],
    "booking_status": ["confirmed", "checked_in", "checked_out", "cancelled"],
    "order_status": ["pending", "preparing", "delivered"],
    "task_status": ["pending", "in_progress", "done"],
    "priority": ["low", "medium", "high"],
}
MENU = {
    "People": ["guest", "staff", "department", "designation", "shift", "role", "user"],
    "Rooms": ["floor", "bed_type", "room_type", "room", "amenity", "room_amenity"],
    "Bookings": ["booking", "booking_room", "check_in", "check_out", "cancellation"],
    "Billing": ["invoice", "invoice_item", "payment", "payment_method", "tax", "discount", "coupon"],
    "Services": ["service_category", "service", "service_order", "menu_category",
                 "menu_item", "food_order", "food_order_item", "laundry_request"],
    "Operations": ["housekeeping_task", "maintenance_request", "supplier", "inventory_item",
                   "purchase_order", "feedback", "notification", "audit_log"],
}


# ---------- helpers ----------
STAFF_ROLES = {"Admin", "Staff"}


def staff_required(f):
    @wraps(f)
    def wrapper(*a, **k):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("main.login", next=request.full_path.rstrip("?")))
        if session.get("role") not in STAFF_ROLES:
            flash("You do not have access to that page.", "danger")
            return redirect(url_for("main.home"))
        return f(*a, **k)
    return wrapper


def login_required(f):
    @wraps(f)
    def wrapper(*a, **k):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("main.login", next=request.full_path.rstrip("?")))
        return f(*a, **k)
    return wrapper


@bp.app_context_processor
def inject():
    return {"MENU": MENU, "nice": lambda t: t.replace("_", " ").title()}


@bp.before_app_request
def guard():
    """1) POST sirf apni hi site se (CSRF), 2) agar user delete/deactive ho gaya to session khatam."""
    if request.endpoint == "static":
        return
    if request.method == "POST":
        origin = request.headers.get("Origin") or request.headers.get("Referer")
        if origin and urlparse(origin).netloc != request.host:
            abort(403)
    uid = session.get("user_id")
    if uid:
        u = db.session.get(User, uid)
        if not u or u.is_deleted or u.status != "active":
            session.clear()
            flash("Your session has ended. Please log in again.", "warning")
            return redirect(url_for("main.login"))


def safe_next(nxt, default):
    """Open-redirect se bachao: sirf apni site ka path (// aur \\ block)."""
    ok = nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt
    return nxt if ok else default


def target_model(col):
    return MODELS[next(iter(col.foreign_keys)).column.table.name]


@bp.app_template_filter("show")
def show(obj, col):
    v = getattr(obj, col.name)
    if v is None:
        return "—"
    if col.foreign_keys:
        r = db.session.get(target_model(col), v)
        return r.label() if r else f"#{v}"
    return v


def get_model(table):
    m = MODELS.get(table)
    if not m:
        abort(404)
    return m


def editable(model):
    return [c for c in model.__table__.columns if c.name not in HIDDEN]


def live_or_404(model, id):
    obj = model.query.filter_by(id=id, is_deleted=False).first()
    if not obj:
        abort(404)
    return obj


def audit(action, table, rec_id):
    if table != "audit_log":
        db.session.add(AuditLog(user_id=session["user_id"], action=action,
                                table_name=table, record_id=rec_id,
                                created_by=session["user_id"]))


def build_fields(model, values):
    out = []
    for c in editable(model):
        required = (not c.nullable) and c.default is None
        f = {"name": c.name, "label": c.name.replace("_id", "").replace("_", " ").title(),
             "required": required, "kind": "text", "options": None, "value": values.get(c.name, "")}
        if c.foreign_keys:
            rows = target_model(c).query.filter_by(is_deleted=False).all()
            f["kind"], f["options"] = "select", [(r.id, r.label()) for r in rows]
        elif c.name in CHOICES:
            f["kind"], f["options"] = "select", [(x, x) for x in CHOICES[c.name]]
        elif isinstance(c.type, db.Text):
            f["kind"] = "textarea"
        elif isinstance(c.type, db.Integer):
            f["kind"] = "number"
        elif isinstance(c.type, db.Float):
            f["kind"] = "number"; f["step"] = "any"
        elif isinstance(c.type, db.DateTime):
            f["kind"] = "datetime-local"
        elif isinstance(c.type, db.Date):
            f["kind"] = "date"
        out.append(f)
    return out


def obj_values(model, obj):
    vals = {}
    for c in editable(model):
        v = getattr(obj, c.name)
        if v is None:
            v = ""
        elif isinstance(v, datetime):
            v = v.strftime("%Y-%m-%dT%H:%M")
        vals[c.name] = str(v)
    vals["status"] = obj.status
    return vals


def parse(model, obj):
    """Server-side validation (HTML5 se aage): type, length, FK, choices, negative."""
    data, errors = {}, []
    for c in editable(model):
        raw = request.form.get(c.name, "").strip()
        nm = c.name.replace("_id", "").replace("_", " ").title()
        if not raw:
            if not c.nullable and c.default is None:
                errors.append(f"{nm} is required.")
            elif obj is not None and c.nullable:
                data[c.name] = None
            continue
        try:
            if c.foreign_keys:
                v = int(raw)
                if not target_model(c).query.filter_by(id=v, is_deleted=False).first():
                    raise ValueError
            elif isinstance(c.type, db.Integer):
                v = int(raw)
            elif isinstance(c.type, db.Float):
                v = float(raw)
            elif isinstance(c.type, db.DateTime):
                v = datetime.strptime(raw, "%Y-%m-%dT%H:%M")
            elif isinstance(c.type, db.Date):
                v = datetime.strptime(raw, "%Y-%m-%d").date()
            else:
                v = raw
                if getattr(c.type, "length", None) and len(raw) > c.type.length:
                    errors.append(f"{nm} must be at most {c.type.length} characters."); continue
                if c.name in CHOICES and raw not in CHOICES[c.name]:
                    errors.append(f"{nm} is invalid."); continue
                if "email" in c.name and "@" not in raw:
                    errors.append("Please enter a valid email address."); continue
            if isinstance(v, (int, float)) and not c.foreign_keys and v < 0:
                errors.append(f"{nm} cannot be negative."); continue
            data[c.name] = v
        except ValueError:
            errors.append(f"{nm} is invalid.")
    if model is User:
        for k in ("email", "username"):
            if k in data:
                data[k] = data[k].lower()
        pw = request.form.get("password", "")
        if pw:
            if len(pw) < 6:
                errors.append("Password must be at least 6 characters.")
            else:
                data["password_hash"] = generate_password_hash(pw)
        elif obj is None:
            errors.append("Password is required.")
    return data, errors


def extra_checks(model, data, errors, obj):
    """Business rules."""
    if model is Booking and data.get("check_in") and data.get("check_out"):
        if data["check_out"] <= data["check_in"]:
            errors.append("Check-out date must be after check-in.")
    if model is Feedback and data.get("rating") is not None and not 1 <= data["rating"] <= 5:
        errors.append("Rating must be between 1 and 5.")
    if model is BookingRoom and data.get("room_id") and data.get("booking_id"):
        b = db.session.get(Booking, data["booking_id"])
        q = (db.session.query(BookingRoom).join(Booking, Booking.id == BookingRoom.booking_id)
             .filter(BookingRoom.room_id == data["room_id"], BookingRoom.is_deleted == False,
                     Booking.is_deleted == False, Booking.booking_status != "cancelled",
                     Booking.id != b.id, Booking.check_in < b.check_out, Booking.check_out > b.check_in))
        if obj is not None:
            q = q.filter(BookingRoom.id != obj.id)
        if q.first():
            errors.append("This room is already booked for these dates.")
    if model is Booking and obj is not None and not errors and data.get("check_in") and data.get("check_out"):
        for br in BookingRoom.query.filter_by(booking_id=obj.id, is_deleted=False).all():
            clash = (db.session.query(BookingRoom).join(Booking, Booking.id == BookingRoom.booking_id)
                     .filter(BookingRoom.room_id == br.room_id, BookingRoom.is_deleted == False,
                             Booking.is_deleted == False, Booking.booking_status != "cancelled",
                             Booking.id != obj.id, Booking.check_in < data["check_out"],
                             Booking.check_out > data["check_in"]).first())
            if clash:
                errors.append(f"Room {br.room.room_number} is already booked for these dates.")
                break


# ---------- auth ----------
@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        name, phone = f.get("full_name", "").strip(), f.get("phone", "").strip()
        e, p, p2 = f.get("email", "").strip().lower(), f.get("password", ""), f.get("confirm", "")
        errs = []
        if len(name) < 3: errs.append("Please enter your full name.")
        if "@" not in e or "." not in e: errs.append("Please enter a valid email address.")
        if len(phone) < 7 or not all(ch.isdigit() or ch in "+- " for ch in phone):
            errs.append("Please enter a valid phone number.")
        if len(p) < 6: errs.append("Password must be at least 6 characters.")
        if p != p2: errs.append("Passwords do not match.")
        if User.query.filter_by(email=e).first(): errs.append("An account with this email already exists.")
        if errs:
            for x in errs: flash(x, "danger")
            return render_template("register.html", form=f)
        role = Role.query.filter_by(name="Guest").first() or Role(name="Guest", description="Hotel guest")
        db.session.add(role); db.session.flush()
        u = User(username=e, email=e, password_hash=generate_password_hash(p), role_id=role.id)
        db.session.add(u); db.session.flush()
        db.session.add(Guest(full_name=name, phone=phone, email=e, user_id=u.id, created_by=u.id))
        db.session.commit()
        flash("Account created. Please sign in.", "success")
        return redirect(url_for("main.login"))          # PRG
    return render_template("register.html", form={})


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ident = request.form.get("email", "").strip().lower()
        u = User.query.filter(or_(User.email == ident, User.username == ident), User.is_deleted == False).first()
        if u and u.status == "active" and check_password_hash(u.password_hash, request.form.get("password", "")):
            session.clear()
            session.update(user_id=u.id, username=u.username, role=u.role.name)
            nxt = request.args.get("next") or request.form.get("next") or ""
            target = safe_next(nxt, url_for("main.dashboard") if u.role.name in STAFF_ROLES else url_for("main.home"))
            resp = make_response(redirect(target))
            resp.set_cookie("last_user", u.email, max_age=30 * 86400, httponly=True, samesite="Lax")  # cookie
            flash(f"Welcome back, {u.username}!", "success")
            return resp
        flash("Invalid email or password.", "danger")
        nxt = request.args.get("next") or request.form.get("next")
        return redirect(url_for("main.login", next=nxt) if nxt else url_for("main.login"))   # PRG
    return render_template("login.html", last_user=request.cookies.get("last_user", ""))


@bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("main.login"))


# ---------- dashboard ----------
@bp.route("/dashboard")
@staff_required
def dashboard():
    live = lambda m: m.query.filter_by(is_deleted=False)
    revenue = (db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0))
               .filter(Payment.is_deleted == False).scalar())
    stats = [("Guests", live(Guest).count()), ("Rooms", live(Room).count()),
             ("Available Rooms", live(Room).filter_by(room_status="available").count()),
             ("Active Bookings", live(Booking).filter(Booking.booking_status.in_(["confirmed", "checked_in"])).count()),
             ("Revenue", f"{revenue:,.0f}")]
    recent = live(Booking).order_by(Booking.id.desc()).limit(5).all()
    return render_template("dashboard.html", stats=stats, recent=recent)


# ---------- generic CRUD ----------
@bp.route("/manage/<table>/")
@staff_required
def list_view(table):
    model = get_model(table)
    q = model.query.filter_by(is_deleted=False)
    search, status = request.args.get("q", "").strip(), request.args.get("status", "")
    text_cols = [c for c in editable(model) if isinstance(c.type, db.String) and not c.foreign_keys]
    if search and text_cols:                                   # SEARCH
        q = q.filter(or_(*[c.ilike(f"%{search}%") for c in text_cols]))
    if status in ("active", "deactive"):                       # FILTER
        q = q.filter_by(status=status)
    page = q.order_by(model.id.desc()).paginate(page=request.args.get("page", 1, type=int),
                                                 per_page=10, error_out=False)
    return render_template("list.html", table=table, cols=editable(model), page=page,
                           search=search, status=status)


@bp.route("/manage/<table>/add", methods=["GET", "POST"])
@bp.route("/manage/<table>/<int:id>/edit", methods=["GET", "POST"])
@staff_required
def form_view(table, id=None):
    model = get_model(table)
    obj = live_or_404(model, id) if id else None

    def again(values):
        fields = build_fields(model, values)
        return render_template("form.html", table=table, fields=fields, obj=obj,
                               status=values.get("status", "active"), is_user=model is User)

    if request.method == "GET":
        return again(obj_values(model, obj) if obj else {})
    data, errors = parse(model, obj)
    extra_checks(model, data, errors, obj)
    if errors:
        for e in errors: flash(e, "danger")
        return again(request.form.to_dict())
    me = session["user_id"]
    if obj is None:
        obj = model(created_by=me); db.session.add(obj)
    else:
        obj.updated_by = me
    for k, v in data.items():
        setattr(obj, k, v)
    if request.form.get("status") in ("active", "deactive"):
        obj.status = request.form["status"]
    try:
        db.session.flush()
        audit("update" if id else "create", table, obj.id)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("This record already exists (duplicate unique value).", "danger")
        return again(request.form.to_dict())
    flash("Record saved successfully.", "success")
    return redirect(url_for("main.list_view", table=table))       # PRG


@bp.route("/manage/<table>/<int:id>/delete", methods=["POST"])
@staff_required
def delete_view(table, id):
    model = get_model(table)
    if session.get("role") != "Admin":
        flash("Only an Admin can delete records.", "danger")
        return redirect(url_for("main.list_view", table=table))
    obj = live_or_404(model, id)
    if model is User and obj.id == session["user_id"]:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("main.list_view", table=table))
    obj.is_deleted, obj.deleted_at, obj.deleted_by = True, datetime.utcnow(), session["user_id"]  # SOFT DELETE
    audit("delete", table, obj.id)
    db.session.commit()
    flash("Record deleted.", "info")
    return redirect(url_for("main.list_view", table=table))


@bp.route("/manage/<table>/<int:id>/toggle", methods=["POST"])
@staff_required
def toggle_view(table, id):
    obj = live_or_404(get_model(table), id)
    obj.status = "deactive" if obj.status == "active" else "active"
    obj.updated_by = session["user_id"]
    audit("status", table, obj.id)
    db.session.commit()
    return redirect(request.referrer or url_for("main.list_view", table=table))


# =====================================================================
#                       GUEST PORTAL (public + guests)
# =====================================================================
def my_guest():
    return Guest.query.filter_by(user_id=session.get("user_id"), is_deleted=False).first()


def parse_dates(ci_raw, co_raw):
    try:
        ci = datetime.strptime(ci_raw, "%Y-%m-%d").date()
        co = datetime.strptime(co_raw, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None, None, "Please choose valid check-in and check-out dates."
    if ci < date.today():
        return ci, co, "Check-in cannot be in the past."
    if co <= ci:
        return ci, co, "Check-out must be after check-in."
    return ci, co, None


def free_rooms(ci=None, co=None, type_id=None, max_price=None, skip_booking=None):
    """Rooms that are bookable (and free for ci..co if dates are given)."""
    q = Room.query.filter(Room.is_deleted == False, Room.status == "active",
                          Room.room_status != "maintenance")
    if ci and co:
        busy = (db.session.query(BookingRoom.room_id)
                .join(Booking, Booking.id == BookingRoom.booking_id)
                .filter(BookingRoom.is_deleted == False, Booking.is_deleted == False,
                        Booking.booking_status != "cancelled",
                        Booking.check_in < co, Booking.check_out > ci))
        if skip_booking:
            busy = busy.filter(Booking.id != skip_booking)
        q = q.filter(~Room.id.in_([r[0] for r in busy.all()]))
    if type_id:
        q = q.filter(Room.room_type_id == type_id)
    if max_price:
        q = q.filter(Room.price_per_night <= max_price)
    return q.order_by(Room.price_per_night).all()


def find_coupon(code):
    if not code:
        return None
    c = Coupon.query.filter_by(code=code.strip().upper(), is_deleted=False, status="active").first()
    return c if c and (c.valid_until is None or c.valid_until >= date.today()) else None


def price(rate, nights, coupon):
    sub = rate * nights
    pct = coupon.discount.percent if coupon else 0
    after = sub * (1 - pct / 100)
    tax = Tax.query.filter_by(is_deleted=False, status="active").first()
    trate = tax.rate if tax else 0
    return {"subtotal": sub, "discount": sub * pct / 100, "pct": pct, "tax_rate": trate,
            "tax": after * trate / 100, "total": round(after * (1 + trate / 100), 2), "tax_obj": tax}


def validate_stay(room, src, skip=None):
    errors = []
    ci, co, err = parse_dates(src.get("check_in", ""), src.get("check_out", ""))
    try:
        adults = int(src.get("adults") or 1)
    except ValueError:
        adults = 0
    code, notes = (src.get("coupon") or "").strip(), (src.get("notes") or "").strip()[:500]
    coupon = find_coupon(code)
    if err:
        errors.append(err)
    elif room.id not in [r.id for r in free_rooms(ci, co, skip_booking=skip)]:
        errors.append("This room is not available for the selected dates.")
    if not 1 <= adults <= room.room_type.max_guests:
        errors.append(f"This room allows 1 to {room.room_type.max_guests} guests.")
    if code and not coupon:
        errors.append("Coupon code is invalid or expired.")
    nights = 0 if err else (co - ci).days
    quote = None if err else price(room.price_per_night, nights, coupon)
    return dict(ci=ci, co=co, adults=adults, coupon=coupon, notes=notes,
                quote=quote, nights=nights, errors=errors)


def rebuild_invoice_items(inv, room, nights, quote, uid):
    for it in InvoiceItem.query.filter_by(invoice_id=inv.id, is_deleted=False).all():
        it.is_deleted, it.deleted_at, it.deleted_by = True, datetime.utcnow(), uid
    db.session.add(InvoiceItem(invoice_id=inv.id, created_by=uid, quantity=nights,
                               description=f"Room {room.room_number} ({room.room_type.name})",
                               unit_price=room.price_per_night))
    if quote["discount"] > 0:
        db.session.add(InvoiceItem(invoice_id=inv.id, created_by=uid, quantity=1,
                                   description=f"Coupon discount ({quote['pct']:.0f}%)",
                                   unit_price=-round(quote["discount"], 2)))


def booking_parts(b):
    br = BookingRoom.query.filter_by(booking_id=b.id, is_deleted=False).first()
    inv = Invoice.query.filter_by(booking_id=b.id, is_deleted=False).first()
    paid = 0
    if inv:
        paid = (db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0))
                .filter(Payment.invoice_id == inv.id, Payment.is_deleted == False).scalar())
    return br, inv, paid


def pay_method(name):
    pm = PaymentMethod.query.filter_by(name=name).first()
    if not pm:
        pm = PaymentMethod(name=name)
        db.session.add(pm)
    pm.is_deleted = False
    db.session.flush()
    return pm


def record_payment(inv, amount, method, txn, uid, brand=None, last4=None, note=None):
    """amount > 0 = payment, amount < 0 = refund."""
    p = Payment(invoice_id=inv.id, payment_method_id=pay_method(method).id, amount=amount,
                paid_on=date.today(), transaction_id=txn, card_brand=brand, card_last4=last4,
                note=note, created_by=uid)
    db.session.add(p)
    db.session.flush()
    return p


def notify(user_id, message):
    if user_id:
        db.session.add(Notification(user_id=user_id, message=message[:250], created_by=user_id))


def booking_mail(b, subject, lines):
    """Guest ko confirmation email (SMTP set ho to real, warna console). True = real email gayi."""
    g = b.guest
    link = url_for("main.booking_detail", id=b.id, _external=True)
    body = f"Dear {g.full_name},\n\n" + "\n".join(lines) + f"\n\nView your booking: {link}\n\n- Hotel Management System"
    return send_email(g.email, subject, body)


def my_booking_or_404(id):
    g = my_guest()
    b = Booking.query.filter_by(id=id, is_deleted=False).first_or_404()
    if not g or b.guest_id != g.id:
        abort(404)
    return b


@bp.route("/")
def home():
    types = RoomType.query.filter_by(is_deleted=False, status="active").all()
    return render_template("home.html", types=types, today=date.today())


@bp.route("/rooms")
def rooms():
    a = request.args
    ci_raw, co_raw = a.get("check_in", ""), a.get("check_out", "")
    type_id, max_price = a.get("room_type", type=int), a.get("max_price", type=float)
    guests = a.get("guests", 1, type=int) or 1
    error, nights, results = None, 0, []
    if ci_raw and co_raw:
        ci, co, error = parse_dates(ci_raw, co_raw)
        if not error:
            nights = (co - ci).days
            results = free_rooms(ci, co, type_id, max_price)
    else:
        results = free_rooms(None, None, type_id, max_price)
    results = [r for r in results if r.room_type.max_guests >= guests]
    types = RoomType.query.filter_by(is_deleted=False).all()
    return render_template("rooms.html", results=results, types=types, error=error, nights=nights,
                           ci=ci_raw, co=co_raw, guests=guests, type_id=type_id,
                           max_price=a.get("max_price", ""), today=date.today())


@bp.route("/rooms/<int:room_id>/book", methods=["GET", "POST"])
@login_required
def book(room_id):
    if session.get("role") != "Guest" or not my_guest():
        flash("Please sign in with a guest account to book a room.", "warning")
        return redirect(url_for("main.home"))
    room = Room.query.filter_by(id=room_id, is_deleted=False, status="active").first_or_404()
    src = request.form if request.method == "POST" else request.args
    data = validate_stay(room, src) if (request.method == "POST" or src.get("check_in")) else None
    if request.method == "POST" and request.form.get("action") != "quote" and not data["errors"]:
        uid, guest = session["user_id"], my_guest()
        b = Booking(guest_id=guest.id, check_in=data["ci"], check_out=data["co"], adults=data["adults"],
                    booking_status="confirmed", notes=data["notes"], created_by=uid,
                    coupon_id=data["coupon"].id if data["coupon"] else None)
        db.session.add(b); db.session.flush()
        db.session.add(BookingRoom(booking_id=b.id, room_id=room.id, rate=room.price_per_night, created_by=uid))
        q = data["quote"]
        inv = Invoice(invoice_no=f"INV-{b.id:05d}", booking_id=b.id, total=q["total"], created_by=uid,
                      tax_id=q["tax_obj"].id if q["tax_obj"] else None, issue_date=date.today())
        db.session.add(inv); db.session.flush()
        rebuild_invoice_items(inv, room, data["nights"], q, uid)
        db.session.add(Notification(user_id=uid, message=f"Booking #{b.id} confirmed", created_by=uid))
        audit("create", "booking", b.id)
        db.session.commit()
        emailed = booking_mail(b, f"Booking #{b.id} confirmed", [
            f"Your booking #{b.id} is confirmed.",
            f"Room {room.room_number} ({room.room_type.name}), {data['ci']} to {data['co']} ({data['nights']} night(s)).",
            f"Invoice {inv.invoice_no}: total {money(q['total'])}. Please complete the payment from your booking page."])
        flash(f"Booking #{b.id} confirmed! Invoice {inv.invoice_no}, total {money(q['total'])}. "
              "Pay now from the page below to secure your stay." + (" A confirmation email has been sent." if emailed else ""),
              "success")
        return redirect(url_for("main.booking_detail", id=b.id))           # PRG
    return render_template("book.html", room=room, booking=None, form=src, today=date.today(),
                           errors=data["errors"] if data else [], quote=data["quote"] if data else None,
                           nights=data["nights"] if data else 0)


@bp.route("/my/bookings")
@login_required
def my_bookings():
    g = my_guest()
    bookings = (Booking.query.filter_by(guest_id=g.id, is_deleted=False).order_by(Booking.id.desc()).all()
                if g else [])
    rows = []
    for b in bookings:
        br, inv, paid = booking_parts(b)
        rows.append(dict(b=b, room=br.room if br else None, total=inv.total if inv else 0, paid=paid))
    return render_template("my_bookings.html", rows=rows)


@bp.route("/my/bookings/<int:id>")
@login_required
def booking_detail(id):
    b = my_booking_or_404(id)
    br, inv, paid = booking_parts(b)
    items = InvoiceItem.query.filter_by(invoice_id=inv.id, is_deleted=False).all() if inv else []
    return render_template("booking_detail.html", b=b, room=br.room, inv=inv, items=items, paid=paid,
                           nights=(b.check_out - b.check_in).days,
                           can_change=b.booking_status == "confirmed" and b.check_in > date.today())


@bp.route("/my/bookings/<int:id>/edit", methods=["GET", "POST"])
@login_required
def booking_edit(id):
    b = my_booking_or_404(id)
    br, inv, paid = booking_parts(b)
    if b.booking_status != "confirmed" or b.check_in <= date.today():
        flash("This booking can no longer be changed.", "warning")
        return redirect(url_for("main.booking_detail", id=id))
    room = br.room
    src = request.form if request.method == "POST" else {
        "check_in": str(b.check_in), "check_out": str(b.check_out), "adults": b.adults,
        "notes": b.notes or "", "coupon": b.coupon.code if b.coupon else ""}
    data = validate_stay(room, src, skip=b.id)
    if request.method == "POST" and request.form.get("action") != "quote" and not data["errors"]:
        uid, q = session["user_id"], data["quote"]
        b.check_in, b.check_out, b.adults, b.notes = data["ci"], data["co"], data["adults"], data["notes"]
        b.coupon_id = data["coupon"].id if data["coupon"] else None
        b.updated_by = uid
        inv.total, inv.tax_id, inv.updated_by = q["total"], (q["tax_obj"].id if q["tax_obj"] else None), uid
        rebuild_invoice_items(inv, room, data["nights"], q, uid)
        msg = "Your booking has been updated."
        excess = round(paid - q["total"], 2)
        if excess > 0:                                     # nayi dates sasti hain -> farq wapis
            ok, ref, err = get_gateway().refund(excess)
            if ok:
                record_payment(inv, -excess, "Card", ref, uid, note="Refund - booking shortened/cheaper")
                msg += f" {money(excess)} has been refunded (ref {ref})."
        audit("update", "booking", b.id)
        db.session.commit()
        booking_mail(b, f"Booking #{b.id} updated", [msg, f"New dates: {b.check_in} to {b.check_out}.",
                                                     f"New total: {money(q['total'])}."])
        flash(msg, "success")
        return redirect(url_for("main.booking_detail", id=id))              # PRG
    return render_template("book.html", room=room, booking=b, form=src, today=date.today(),
                           errors=data["errors"] if request.method == "POST" else [],
                           quote=data["quote"], nights=data["nights"])


@bp.route("/my/bookings/<int:id>/cancel", methods=["POST"])
@login_required
def booking_cancel(id):
    b = my_booking_or_404(id)
    if b.booking_status != "confirmed":
        flash("Only confirmed bookings can be cancelled.", "warning")
        return redirect(url_for("main.booking_detail", id=id))
    _, inv, paid = booking_parts(b)
    uid = session["user_id"]
    refund = round(paid, 2) if (b.check_in - date.today()).days >= 2 else 0   # full refund if 2+ days ahead
    ref = None
    if refund > 0:
        ok, ref, err = get_gateway().refund(refund)
        if not ok:
            flash(f"Refund could not be processed ({err}). Booking was not cancelled.", "danger")
            return redirect(url_for("main.booking_detail", id=id))
        last = (Payment.query.filter(Payment.invoice_id == inv.id, Payment.is_deleted == False,
                                     Payment.amount > 0).order_by(Payment.id.desc()).first())
        record_payment(inv, -refund, last.payment_method.name if last else "Card", ref, uid,
                       note="Refund - booking cancelled")
    b.booking_status, b.updated_by = "cancelled", uid
    db.session.add(Cancellation(booking_id=b.id, refund_amount=refund, created_by=uid,
                                reason=request.form.get("reason", "").strip()[:500] or "Cancelled by guest"))
    notify(uid, f"Booking #{b.id} cancelled" + (f", refund {refund:,.0f}" if refund else ""))
    audit("cancel", "booking", b.id)
    db.session.commit()
    if refund > 0:
        msg = f"Booking #{b.id} cancelled. {money(refund)} has been refunded (ref {ref})."
    elif paid > 0:
        msg = f"Booking #{b.id} cancelled. No refund, as it was cancelled less than 2 days before check-in."
    else:
        msg = f"Booking #{b.id} cancelled. No payment was taken, so nothing to refund."
    booking_mail(b, f"Booking #{b.id} cancelled", [msg])
    flash(msg, "info")
    return redirect(url_for("main.booking_detail", id=id))


@bp.route("/my/bookings/<int:id>/pay", methods=["POST"])
@login_required
def booking_pay(id):
    """Purana 'instant demo pay' button ab secure checkout page par le jata hai."""
    my_booking_or_404(id)
    return redirect(url_for("main.booking_checkout", id=id))


@bp.route("/my/bookings/<int:id>/checkout", methods=["GET", "POST"])
@login_required
def booking_checkout(id):
    b = my_booking_or_404(id)
    br, inv, paid = booking_parts(b)
    if not inv or b.booking_status not in ("confirmed", "checked_in"):
        flash("Nothing to pay for this booking.", "warning")
        return redirect(url_for("main.booking_detail", id=id))
    balance = round(inv.total - paid, 2)
    if balance <= 0:
        flash("This booking is already fully paid.", "info")
        return redirect(url_for("main.booking_detail", id=id))
    gw = get_gateway()

    def page(form):
        return render_template("checkout.html", b=b, room=br.room, inv=inv, paid=paid, balance=balance,
                               gateway=gw, form=form, token=session["pay_token"],
                               nights=(b.check_out - b.check_in).days)

    if request.method == "GET":
        session["pay_token"] = secrets.token_hex(16)
        return page({})

    # --- POST: pay ---
    f = request.form
    expected = session.get("pay_token", "")
    if not expected or not hmac.compare_digest(expected, f.get("token", "")):
        flash("This payment form has expired or was already submitted. Please check your booking and try again.", "warning")
        return redirect(url_for("main.booking_detail", id=id))      # double-click / refresh = double charge nahi
    errors = []
    try:
        amount = round(float(f.get("amount", "")), 2)
        if not 0.01 <= amount <= balance:
            errors.append(f"Amount must be between 0.01 and {balance:,.2f}.")
    except ValueError:
        amount = 0
        errors.append("Please enter a valid amount.")
    card_errors, card = validate_card(f.get("card_name"), f.get("card_number"), f.get("expiry"), f.get("cvv"))
    errors += card_errors
    safe_form = {"card_name": f.get("card_name", ""), "expiry": f.get("expiry", ""), "amount": f.get("amount", "")}
    if errors:
        for e in errors:
            flash(e, "danger")
        return page(safe_form)

    uid = session["user_id"]
    session.pop("pay_token", None)                               # token ek hi baar use hota hai
    ok, txn, err = gw.charge(card["number"], amount, f"BOOKING-{b.id}")
    if not ok:
        audit("pay_failed", "booking", b.id)
        db.session.commit()
        session["pay_token"] = secrets.token_hex(16)             # naya token taake dobara try kar sakein
        flash(f"Payment failed: {err} You have not been charged.", "danger")
        return page(safe_form)
    p = record_payment(inv, amount, "Card", txn, uid, card["brand"], card["last4"], "Online payment")
    left = round(balance - amount, 2)
    notify(uid, f"Payment of {amount:,.0f} received for booking #{b.id} (ref {txn})")
    audit("payment", "booking", b.id)
    db.session.commit()
    emailed = booking_mail(b, f"Payment received - booking #{b.id}", [
        f"We received your payment of {money(amount)} (ref {txn}) by {card['brand']} ending {card['last4']}.",
        "Your booking is fully paid. Thank you!" if left <= 0 else f"Remaining balance: {money(left)}."])
    flash(f"Payment of {money(amount)} successful (ref {txn})." +
          (" Your booking is fully paid. Thank you!" if left <= 0 else f" Remaining balance: {money(left)}.") +
          (" A receipt has been emailed to you." if emailed else ""), "success")
    return redirect(url_for("main.payment_receipt", pid=p.id))        # PRG


@bp.route("/my/payments/<int:pid>/receipt")
@login_required
def payment_receipt(pid):
    p = Payment.query.filter_by(id=pid, is_deleted=False).first_or_404()
    inv = db.session.get(Invoice, p.invoice_id)
    b = my_booking_or_404(inv.booking_id)
    br, inv, paid = booking_parts(b)
    return render_template("receipt.html", p=p, b=b, inv=inv, room=br.room, paid=paid,
                           balance=round(inv.total - paid, 2))


# =====================================================================
#                       FRONT DESK (staff / admin)
# =====================================================================
def booking_row(b):
    br, inv, paid = booking_parts(b)
    return dict(b=b, room=br.room if br else None, inv=inv, paid=paid,
                balance=round((inv.total if inv else 0) - paid, 2))


@bp.route("/staff/front-desk")
@staff_required
def front_desk():
    live = Booking.query.filter_by(is_deleted=False)
    arrivals = live.filter(Booking.booking_status == "confirmed").order_by(Booking.check_in).limit(50).all()
    inhouse = live.filter(Booking.booking_status == "checked_in").order_by(Booking.check_out).all()
    return render_template("front_desk.html", today=date.today(),
                           arrivals=[booking_row(x) for x in arrivals],
                           inhouse=[booking_row(x) for x in inhouse])


@bp.route("/staff/bookings/<int:id>/checkin", methods=["POST"])
@staff_required
def desk_checkin(id):
    b, uid = live_or_404(Booking, id), session["user_id"]
    if b.booking_status != "confirmed":
        flash("Only confirmed bookings can be checked in.", "warning")
    elif b.check_in > date.today():
        flash(f"Too early - check-in date is {b.check_in}.", "warning")
    else:
        br, _, _ = booking_parts(b)
        staff = Staff.query.filter_by(user_id=uid, is_deleted=False).first()
        b.booking_status, b.updated_by = "checked_in", uid
        if br:
            br.room.room_status = "occupied"
        db.session.add(CheckIn(booking_id=b.id, checkin_time=datetime.now(),
                               staff_id=staff.id if staff else None, created_by=uid))
        notify(b.guest.user_id, f"You are checked in for booking #{b.id}. Enjoy your stay!")
        audit("checkin", "booking", b.id)
        db.session.commit()
        booking_mail(b, f"Welcome - booking #{b.id} checked in",
                     [f"You are now checked in (room {br.room.room_number if br else '-'}). Enjoy your stay!"])
        flash(f"Booking #{b.id} checked in. Room is now occupied.", "success")
    return redirect(url_for("main.front_desk"))


@bp.route("/staff/bookings/<int:id>/collect", methods=["POST"])
@staff_required
def desk_collect(id):
    """Front desk par cash / card (POS) payment le kar record karna."""
    b, uid = live_or_404(Booking, id), session["user_id"]
    _, inv, paid = booking_parts(b)
    method = request.form.get("method", "Cash")
    try:
        amount = round(float(request.form.get("amount", "")), 2)
    except ValueError:
        amount = 0
    balance = round((inv.total if inv else 0) - paid, 2)
    if not inv or method not in ("Cash", "Card") or not 0.01 <= amount <= balance:
        flash(f"Enter a valid amount (max {balance:,.2f}) and method.", "danger")
    else:
        txn = f"{method[:4].upper()}-{secrets.token_hex(4).upper()}"
        record_payment(inv, amount, method, txn, uid, note="Collected at front desk")
        notify(b.guest.user_id, f"Payment of {amount:,.0f} received at front desk for booking #{b.id}")
        audit("payment", "booking", b.id)
        db.session.commit()
        booking_mail(b, f"Payment received - booking #{b.id}", [
            f"We received {money(amount)} ({method}, ref {txn}) at the front desk.",
            f"Remaining balance: {money(balance - amount)}."])
        flash(f"{money(amount)} received by {method} (ref {txn}). Balance: {money(balance - amount)}.", "success")
    return redirect(url_for("main.front_desk"))


@bp.route("/staff/bookings/<int:id>/checkout", methods=["POST"])
@staff_required
def desk_checkout(id):
    b, uid = live_or_404(Booking, id), session["user_id"]
    br, inv, paid = booking_parts(b)
    balance = round((inv.total if inv else 0) - paid, 2)
    if b.booking_status != "checked_in":
        flash("Only checked-in bookings can be checked out.", "warning")
    elif balance > 0:
        flash(f"Outstanding balance {money(balance)} - collect payment before check-out.", "danger")
    else:
        staff = Staff.query.filter_by(user_id=uid, is_deleted=False).first()
        b.booking_status, b.updated_by = "checked_out", uid
        db.session.add(CheckOut(booking_id=b.id, checkout_time=datetime.now(),
                                staff_id=staff.id if staff else None, created_by=uid))
        if br:
            br.room.room_status = "available"
            db.session.add(HousekeepingTask(room_id=br.room_id, task="Clean room after check-out",
                                            task_status="pending", created_by=uid))
        notify(b.guest.user_id, f"Checked out of booking #{b.id}. Thank you for staying with us!")
        audit("checkout", "booking", b.id)
        db.session.commit()
        booking_mail(b, f"Thank you - booking #{b.id}", ["You have been checked out. Thank you for staying with us!"])
        flash(f"Booking #{b.id} checked out. Room released and a housekeeping task created.", "success")
    return redirect(url_for("main.front_desk"))


@bp.route("/my/profile", methods=["GET", "POST"])
@login_required
def profile():
    g = my_guest()
    if not g:
        flash("Profile is only available for guest accounts.", "warning")
        return redirect(url_for("main.home"))
    if request.method == "POST":
        f, errs = request.form, []
        name, phone = f.get("full_name", "").strip(), f.get("phone", "").strip()
        cnic = f.get("cnic", "").strip() or None
        if len(name) < 3: errs.append("Please enter your full name.")
        if len(phone) < 7 or not all(ch.isdigit() or ch in "+- " for ch in phone):
            errs.append("Please enter a valid phone number.")
        if cnic and Guest.query.filter(Guest.cnic == cnic, Guest.id != g.id).first():
            errs.append("This ID number is already registered.")
        if errs:
            for x in errs: flash(x, "danger")
            return render_template("profile.html", g=g, form=f)
        g.full_name, g.phone, g.cnic = name, phone, cnic
        g.city, g.address = f.get("city", "").strip()[:60], f.get("address", "").strip()[:200]
        g.updated_by = session["user_id"]
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("main.profile"))                            # PRG
    return render_template("profile.html", g=g, form={"full_name": g.full_name, "phone": g.phone,
                           "cnic": g.cnic or "", "city": g.city or "", "address": g.address or ""})
