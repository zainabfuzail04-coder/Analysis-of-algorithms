"""41 SQLAlchemy models. Har table mein Base ki audit + soft-delete columns hain."""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# ---- chote helpers taake models short rahein ----
def S(n=100, **k): return db.Column(db.String(n), **k)
def I(**k): return db.Column(db.Integer, **k)
def F(**k): return db.Column(db.Float, **k)
def T(**k): return db.Column(db.Text, **k)
def D(**k): return db.Column(db.Date, **k)
def DT(**k): return db.Column(db.DateTime, **k)
def FK(table, **k): return db.Column(db.Integer, db.ForeignKey(f"{table}.id"), **k)
def R(model, **k): return db.relationship(model, **k)


class Base(db.Model):
    """Sir ki notes: har table mein ye columns (soft delete + audit)."""
    __abstract__ = True
    id = db.Column(db.Integer, primary_key=True)
    status = S(10, default="active")                 # active / deactive
    is_deleted = db.Column(db.Boolean, default=False)  # soft delete
    created_at = DT(default=datetime.utcnow)
    created_by = I()
    updated_at = DT(default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = I()
    deleted_at = DT()
    deleted_by = I()

    def label(self):
        for a in ("name", "title", "room_number", "username", "full_name",
                  "invoice_no", "transaction_id", "code", "message", "issue", "task"):
            v = getattr(self, a, None)
            if v:
                return str(v)
        return f"{type(self).__name__} #{self.id}"


# ---------------- People ----------------
class Role(Base):
    name = S(50, unique=True, nullable=False); description = S(200)

class User(Base):
    username = S(50, unique=True, nullable=False)
    email = S(120, unique=True, nullable=False)
    password_hash = S(255, nullable=False)
    role_id = FK("role", nullable=False); role = R("Role")

class Guest(Base):
    full_name = S(100, nullable=False); email = S(120); phone = S(20, nullable=False)
    cnic = S(20, unique=True); address = S(200); city = S(60)
    user_id = FK("user"); user = R("User")

class Department(Base):
    name = S(80, unique=True, nullable=False); description = S(200)

class Designation(Base):
    title = S(80, nullable=False)
    department_id = FK("department", nullable=False); department = R("Department", backref="designations")

class Staff(Base):
    full_name = S(100, nullable=False); phone = S(20); salary = F(); hire_date = D()
    department_id = FK("department", nullable=False); department = R("Department")
    designation_id = FK("designation"); designation = R("Designation")
    user_id = FK("user"); user = R("User")

class Shift(Base):
    staff_id = FK("staff", nullable=False); staff = R("Staff")
    shift_date = D(nullable=False); start_time = S(10, nullable=False); end_time = S(10, nullable=False)

# ---------------- Rooms ----------------
class Floor(Base):
    number = I(unique=True, nullable=False); description = S(100)

class BedType(Base):
    name = S(50, unique=True, nullable=False); capacity = I(default=1)

class RoomType(Base):
    name = S(60, unique=True, nullable=False); description = S(200)
    base_price = F(nullable=False); max_guests = I(default=2)
    bed_type_id = FK("bed_type"); bed_type = R("BedType")

class Room(Base):
    room_number = S(10, unique=True, nullable=False)
    floor_id = FK("floor", nullable=False); floor = R("Floor", backref="rooms")
    room_type_id = FK("room_type", nullable=False); room_type = R("RoomType", backref="rooms")
    price_per_night = F(nullable=False)
    room_status = S(20, default="available")   # available/occupied/maintenance

class Amenity(Base):
    name = S(60, unique=True, nullable=False); description = S(200)

class RoomAmenity(Base):
    room_id = FK("room", nullable=False); room = R("Room", backref="amenity_links")
    amenity_id = FK("amenity", nullable=False); amenity = R("Amenity")

# ---------------- Billing setup ----------------
class PaymentMethod(Base):
    name = S(50, unique=True, nullable=False)

class Discount(Base):
    name = S(60, nullable=False); percent = F(nullable=False)

class Coupon(Base):
    code = S(30, unique=True, nullable=False); valid_until = D()
    discount_id = FK("discount", nullable=False); discount = R("Discount")

class Tax(Base):
    name = S(50, nullable=False); rate = F(nullable=False)

# ---------------- Bookings ----------------
class Booking(Base):
    guest_id = FK("guest", nullable=False); guest = R("Guest", backref="bookings")
    check_in = D(nullable=False); check_out = D(nullable=False); adults = I(default=1)
    booking_status = S(20, default="confirmed")   # confirmed/checked_in/checked_out/cancelled
    coupon_id = FK("coupon"); coupon = R("Coupon")
    notes = T()
    def label(self): return f"Booking #{self.id}"

class BookingRoom(Base):
    booking_id = FK("booking", nullable=False); booking = R("Booking", backref="booking_rooms")
    room_id = FK("room", nullable=False); room = R("Room")
    rate = F(nullable=False)

class CheckIn(Base):
    booking_id = FK("booking", nullable=False); booking = R("Booking")
    checkin_time = DT(nullable=False); staff_id = FK("staff"); staff = R("Staff")

class CheckOut(Base):
    booking_id = FK("booking", nullable=False); booking = R("Booking")
    checkout_time = DT(nullable=False); staff_id = FK("staff"); staff = R("Staff")

class Cancellation(Base):
    booking_id = FK("booking", nullable=False); booking = R("Booking")
    reason = T(); refund_amount = F(default=0)

# ---------------- Invoices & Payments ----------------
class Invoice(Base):
    invoice_no = S(30, unique=True, nullable=False)
    booking_id = FK("booking", nullable=False); booking = R("Booking", backref="invoices")
    tax_id = FK("tax"); tax = R("Tax")
    total = F(nullable=False); issue_date = D()

class InvoiceItem(Base):
    invoice_id = FK("invoice", nullable=False); invoice = R("Invoice", backref="items")
    description = S(150, nullable=False); quantity = I(default=1); unit_price = F(nullable=False)

class Payment(Base):
    invoice_id = FK("invoice", nullable=False); invoice = R("Invoice", backref="payments")
    payment_method_id = FK("payment_method", nullable=False); payment_method = R("PaymentMethod")
    amount = F(nullable=False); paid_on = D()     # amount negative = refund
    transaction_id = S(40); card_brand = S(20); card_last4 = S(4); note = S(150)

# ---------------- Services & Food ----------------
class ServiceCategory(Base):
    name = S(60, unique=True, nullable=False)

class Service(Base):
    name = S(80, nullable=False); price = F(nullable=False)
    category_id = FK("service_category", nullable=False); category = R("ServiceCategory")

class ServiceOrder(Base):
    booking_id = FK("booking", nullable=False); booking = R("Booking")
    service_id = FK("service", nullable=False); service = R("Service")
    quantity = I(default=1)

class MenuCategory(Base):
    name = S(60, unique=True, nullable=False)

class MenuItem(Base):
    name = S(80, nullable=False); price = F(nullable=False)
    category_id = FK("menu_category", nullable=False); category = R("MenuCategory")

class FoodOrder(Base):
    booking_id = FK("booking", nullable=False); booking = R("Booking")
    order_status = S(20, default="pending")      # pending/preparing/delivered

class FoodOrderItem(Base):
    food_order_id = FK("food_order", nullable=False); food_order = R("FoodOrder", backref="items")
    menu_item_id = FK("menu_item", nullable=False); menu_item = R("MenuItem")
    quantity = I(default=1)

class LaundryRequest(Base):
    booking_id = FK("booking", nullable=False); booking = R("Booking")
    items_count = I(nullable=False); price = F(default=0)

# ---------------- Operations ----------------
class HousekeepingTask(Base):
    room_id = FK("room", nullable=False); room = R("Room")
    staff_id = FK("staff"); staff = R("Staff")
    task = S(150, nullable=False); task_status = S(20, default="pending")

class MaintenanceRequest(Base):
    room_id = FK("room", nullable=False); room = R("Room")
    issue = S(200, nullable=False); priority = S(10, default="medium"); reported_on = D()

class Supplier(Base):
    name = S(100, nullable=False); phone = S(20); email = S(120)

class InventoryItem(Base):
    name = S(100, nullable=False); quantity = I(default=0); unit = S(20)
    supplier_id = FK("supplier"); supplier = R("Supplier")

class PurchaseOrder(Base):
    supplier_id = FK("supplier", nullable=False); supplier = R("Supplier")
    inventory_item_id = FK("inventory_item", nullable=False); inventory_item = R("InventoryItem")
    quantity = I(nullable=False); order_date = D()

class Feedback(Base):
    guest_id = FK("guest", nullable=False); guest = R("Guest")
    booking_id = FK("booking"); booking = R("Booking")
    rating = I(nullable=False); comment = T()

class Notification(Base):
    user_id = FK("user", nullable=False); user = R("User")
    message = S(250, nullable=False)

class AuditLog(Base):
    user_id = FK("user"); action = S(20); table_name = S(60); record_id = I()


# table-name -> model (CRUD generic views isi se kaam karte hain)
MODELS = {m.__table__.name: m for m in Base.__subclasses__()}
