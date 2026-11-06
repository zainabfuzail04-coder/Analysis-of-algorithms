"""Demo data: python seed.py  (admin / admin123)"""
from datetime import date, timedelta
from werkzeug.security import generate_password_hash
from app import create_app
from models import *

app = create_app()


def add(model, **kw):
    o = model(**kw); db.session.add(o); db.session.flush(); return o


with app.app_context():
    if User.query.filter_by(username="admin").first():
        print("Data already exists."); raise SystemExit
    admin_role = add(Role, name="Admin", description="Full access")
    staff_role = Role.query.filter_by(name="Staff").first() or add(Role, name="Staff", description="Front desk")
    admin = add(User, username="admin", email="admin@hotel.com",
                password_hash=generate_password_hash("admin123"), role_id=admin_role.id)
    dept = add(Department, name="Front Desk")
    des = add(Designation, title="Receptionist", department_id=dept.id)
    desk = add(User, username="frontdesk", email="staff@hotel.com",
               password_hash=generate_password_hash("staff123"), role_id=staff_role.id)
    add(Staff, full_name="Ali Raza", phone="0300-1111111", salary=60000, user_id=desk.id,
        hire_date=date(2024, 1, 15), department_id=dept.id, designation_id=des.id)
    bed = add(BedType, name="King", capacity=2)
    f1, f2 = add(Floor, number=1, description="Ground"), add(Floor, number=2, description="First")
    deluxe = add(RoomType, name="Deluxe", description="City view", base_price=12000, max_guests=2, bed_type_id=bed.id)
    suite = add(RoomType, name="Suite", description="Luxury", base_price=25000, max_guests=4, bed_type_id=bed.id)
    rooms = [add(Room, room_number=f"{fl.number}0{i}", floor_id=fl.id,
                 room_type_id=(deluxe if i < 3 else suite).id,
                 price_per_night=(12000 if i < 3 else 25000)) for fl in (f1, f2) for i in range(1, 5)]
    wifi = add(Amenity, name="WiFi", description="Free WiFi")
    add(RoomAmenity, room_id=rooms[0].id, amenity_id=wifi.id)
    cash = add(PaymentMethod, name="Cash"); add(PaymentMethod, name="Card")
    tax = add(Tax, name="GST", rate=16)
    disc = add(Discount, name="Winter", percent=10)
    add(Coupon, code="WINTER10", discount_id=disc.id, valid_until=date.today() + timedelta(days=365))
    gu = add(User, username="guest@hotel.com", email="guest@hotel.com", password_hash=generate_password_hash("guest123"),
             role_id=add(Role, name="Guest", description="Hotel guest").id)
    guest = add(Guest, user_id=gu.id, full_name="Ahmed Khan", email="ahmed@mail.com", phone="0321-2222222", cnic="35202-1234567-1", city="Lahore")
    add(Guest, full_name="Sara Ali", email="sara@mail.com", phone="0333-3333333", city="Karachi")
    b = add(Booking, guest_id=guest.id, check_in=date.today(), check_out=date.today() + timedelta(days=2), adults=2)
    add(BookingRoom, booking_id=b.id, room_id=rooms[0].id, rate=12000)
    inv = add(Invoice, invoice_no="INV-001", booking_id=b.id, tax_id=tax.id, total=27840, issue_date=date.today())
    add(InvoiceItem, invoice_id=inv.id, description="Room 2 nights", quantity=2, unit_price=12000)
    add(Payment, invoice_id=inv.id, payment_method_id=cash.id, amount=10000, paid_on=date.today(),
        transaction_id="CASH-SEED01", note="Advance at front desk")
    sc = add(ServiceCategory, name="Spa"); add(Service, name="Massage", price=3000, category_id=sc.id)
    mc = add(MenuCategory, name="Main Course"); add(MenuItem, name="Chicken Karahi", price=1800, category_id=mc.id)
    sup = add(Supplier, name="Fresh Supplies", phone="042-111111")
    add(InventoryItem, name="Towels", quantity=100, unit="pcs", supplier_id=sup.id)
    add(Feedback, guest_id=guest.id, booking_id=b.id, rating=5, comment="Great stay")
    db.session.commit()
    print("Seed done. Admin: admin@hotel.com / admin123  |  Staff: staff@hotel.com / staff123  |  Guest: guest@hotel.com / guest123")
