# Study Guide (Mid ke liye) - Roman Urdu

## Shuru mein kya karna hai (order)
1. Virtual env banao: `python -m venv venv`, activate karo.
2. `pip install flask flask-sqlalchemy`, phir `pip freeze > requirements.txt`.
3. Structure: `app.py`, `models.py`, `views.py`, `templates/`.
4. Pehle models (database design), phir routes, phir templates, phir validation, phir README.

## File by file
- **app.py**: `create_app()` = application factory. Config (SECRET_KEY, DB URI), `db.init_app`, blueprint register, `db.create_all()`.
- **models.py**: `Base` abstract class mein common columns (sir ki notes: is_deleted, created_at/by, updated_at/by, status, deleted_at/by). Har model `Base` se inherit karta hai. `FK()` = foreign key, `db.relationship` = relation (backref se ulta access).
- **views.py**: Blueprint. `login_required` decorator. Generic CRUD: `list_view` (search+filter+paginate), `form_view` (add+edit), `delete_view` (soft delete), `toggle_view` (active/deactive).
- **templates**: `base.html` (navbar, flash) -> baqi sab `{% extends %}` + `{% block content %}`.

## Concepts jo paper mein aayenge
- **Soft delete**: row delete nahi hoti, `is_deleted=True` + deleted_at/by set. Queries mein `filter_by(is_deleted=False)`.
- **Routes**: `@bp.route("/manage/<table>/<int:id>/edit", methods=["GET","POST"])` - variable + converter.
- **PRG**: POST ke baad `redirect()` taake refresh par dobara submit na ho.
- **Session vs cookie**: session server-signed (SECRET_KEY) mein user_id; cookie `last_user` browser mein.
- **Validation**: server-side (`parse()`), HTML5 `required` sirf client-side hai.
- **Password**: `generate_password_hash` / `check_password_hash`, kabhi plain nahi.
- **Search/Filter**: `ilike('%q%')`, `or_()`, `filter_by(status=...)`, `paginate()`.
- **IntegrityError**: unique duplicate par rollback + message.

## Viva sawal
1. Soft delete kya hai, kyun? 2. Factory pattern kyun? 3. PRG kya hai? 4. relationship vs ForeignKey? 5. backref kya karta hai? 6. `abstract = True` ka faida? 7. CSRF kya hai (is project mein Flask-WTF add karke theek hota)? 8. Jinja `extends/block`?

## Payment / security concepts (naye)
- **Luhn algorithm**: card number ka checksum, galat number server par hi pakar leta hai.
- **PCI**: card number/CVV database mein kabhi nahi; sirf last4 + transaction id.
- **Idempotency token**: form mein one-time token, taake refresh/double-click par do baar charge na ho.
- **Refund = negative Payment row**: net paid = sum(amount), isliye balance hamesha sahi rehta hai.
- **CSRF**: dusri site se POST bhejna. Bachao: SameSite cookie + Origin check (poora hal: Flask-WTF token).
- **Open redirect**: `next` parameter sirf `/path` ho, `//` ya `\` wala nahi.
- **Gateway pattern**: `charge()/refund()` wala class, taake Stripe/JazzCash baad mein bina flow badle laga sakein.
