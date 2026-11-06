"""Payment layer: card validation + gateway.

IMPORTANT (PCI): card number / CVV kabhi database mein save nahi hote.
Sirf brand + last4 + transaction id save hota hai.

Gateway badalna ho (Stripe, Safepay, PayFast, JazzCash ...) to bas ek naya class
banao jis mein `charge()` aur `refund()` ho, aur GATEWAYS mein add kar do.
Env var:  PAYMENT_GATEWAY=sandbox   (default)
"""
import os
import re
import secrets
from datetime import date

CURRENCY = "PKR"


def money(x):
    return f"{CURRENCY} {x:,.2f}"


# ---------------- card validation ----------------
def luhn_ok(number):
    total, flip = 0, False
    for ch in reversed(number):
        d = int(ch)
        if flip:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        flip = not flip
    return total % 10 == 0


def card_brand(number):
    if number.startswith("4"):
        return "Visa"
    if re.match(r"^(5[1-5]|2[2-7])", number):
        return "Mastercard"
    if re.match(r"^3[47]", number):
        return "Amex"
    if re.match(r"^(60|65|81|82)", number):
        return "UnionPay/RuPay"
    return "Card"


def validate_card(name, number, expiry, cvv):
    """Returns (errors, clean) ; clean = dict(number, brand, last4)."""
    errors = []
    num = re.sub(r"[\s-]", "", number or "")
    if len((name or "").strip()) < 3:
        errors.append("Please enter the name on the card.")
    if not num.isdigit() or not 13 <= len(num) <= 19 or not luhn_ok(num):
        errors.append("Card number is invalid.")
    m = re.match(r"^\s*(\d{1,2})\s*/\s*(\d{2}|\d{4})\s*$", expiry or "")
    if not m or not 1 <= int(m.group(1)) <= 12:
        errors.append("Expiry must be in MM/YY format.")
    else:
        mm, yy = int(m.group(1)), int(m.group(2))
        yy += 2000 if yy < 100 else 0
        today = date.today()
        if (yy, mm) < (today.year, today.month):
            errors.append("This card has expired.")
    brand = card_brand(num)
    need = 4 if brand == "Amex" else 3
    if not (cvv or "").isdigit() or len(cvv) != need:
        errors.append(f"CVV must be {need} digits.")
    return errors, {"number": num, "brand": brand, "last4": num[-4:] if num else ""}


# ---------------- gateways ----------------
class SandboxGateway:
    """Test-mode gateway: koi asli paisa move nahi hota, lekin flow bilkul real hai
    (approve / decline / transaction id / refund)."""
    name = "sandbox"
    sandbox = True
    DECLINES = {
        "4000000000000002": "Your card was declined by the bank.",
        "4000000000009995": "Insufficient funds on this card.",
        "4000000000000069": "This card has expired.",
        "4000000000000127": "The security code (CVV) is incorrect.",
    }

    def charge(self, number, amount, reference):
        if number in self.DECLINES:
            return False, None, self.DECLINES[number]
        return True, "SBX-" + secrets.token_hex(6).upper(), None

    def refund(self, amount, original_txn=None):
        return True, "RFD-" + secrets.token_hex(6).upper(), None


GATEWAYS = {"sandbox": SandboxGateway}


def get_gateway():
    return GATEWAYS.get(os.environ.get("PAYMENT_GATEWAY", "sandbox"), SandboxGateway)()
