from config import db
from datetime import datetime

ORDER_STATUSES = ('pending', 'paid', 'fulfilled', 'cancelled', 'refunded')
PROMO_DISCOUNT_TYPES = ('percent', 'fixed')


class Product(db.Model):
    """A physical item a business sells through its own storefront (Phase
    4 of the site builder). Price is stored once here and SNAPSHOTTED onto
    each OrderItem at purchase time (see OrderItem.unit_price_cents) -- a
    later price change never rewrites a past order's receipt."""
    __tablename__ = 'product'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)

    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    price_cents = db.Column(db.Integer, nullable=False)
    # A "was" price shown struck through next to price_cents when it's
    # higher than price_cents -- the simplest form of "have sales" (no
    # code to enter, just a marked-down item). See Product.on_sale.
    compare_at_price_cents = db.Column(db.Integer, nullable=True)
    currency = db.Column(db.String(3), nullable=False, default='usd', server_default='usd')

    # Raw Supabase Storage filenames, resolved to public URLs at
    # serialization time -- same convention as Business.logo.
    images = db.Column(db.JSON, nullable=True, default=list)

    sku = db.Column(db.String(64), nullable=True)
    # NULL = unlimited stock. Decremented on a paid order (see the
    # checkout.session.completed webhook handler in routes/payments.py).
    inventory_count = db.Column(db.Integer, nullable=True)

    active = db.Column(db.Boolean, nullable=False, default=True, server_default='true', index=True)
    position = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('products', lazy=True, cascade='all, delete-orphan'))

    def __init__(self, business_id, name, price_cents, description=None, currency='usd',
                 images=None, sku=None, inventory_count=None, active=True, position=0,
                 compare_at_price_cents=None):
        self.business_id = business_id
        self.name = name
        self.price_cents = price_cents
        self.compare_at_price_cents = compare_at_price_cents
        self.description = description
        self.currency = currency
        self.images = images or []
        self.sku = sku
        self.inventory_count = inventory_count
        self.active = active
        self.position = position

    @property
    def on_sale(self):
        return self.compare_at_price_cents is not None and self.compare_at_price_cents > self.price_cents

    def __repr__(self):
        return f'Product({self.id}) business={self.business_id} {self.name!r}'


class PromoCode(db.Model):
    """A business's own discount code for its storefront checkout (owner
    CRUD in routes/commerce.py, applied in business_site_public.py's
    submit_checkout). `code` is matched case-insensitively but stored
    upper-cased so "SAVE10" and "save10" are the same code. Scoped to one
    business, never global -- there is no platform-wide discount concept
    here."""
    __tablename__ = 'promo_code'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)

    code = db.Column(db.String(40), nullable=False)
    discount_type = db.Column(db.String(10), nullable=False)  # 'percent' | 'fixed'
    amount = db.Column(db.Integer, nullable=False)  # percent: 1-100; fixed: cents off

    active = db.Column(db.Boolean, nullable=False, default=True, server_default='true', index=True)
    max_redemptions = db.Column(db.Integer, nullable=True)  # NULL = unlimited
    redemption_count = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    min_subtotal_cents = db.Column(db.Integer, nullable=True)  # NULL = no minimum
    expires_at = db.Column(db.DateTime, nullable=True)  # NULL = never expires

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('promo_codes', lazy=True, cascade='all, delete-orphan'))

    __table_args__ = (db.UniqueConstraint('business_id', 'code', name='uq_promo_code_business_code'),)

    def __init__(self, business_id, code, discount_type, amount, active=True,
                 max_redemptions=None, min_subtotal_cents=None, expires_at=None):
        self.business_id = business_id
        self.code = code.strip().upper()
        self.discount_type = discount_type
        self.amount = amount
        self.active = active
        self.max_redemptions = max_redemptions
        self.min_subtotal_cents = min_subtotal_cents
        self.expires_at = expires_at

    def error_for(self, subtotal_cents):
        """Returns an error string, or None if this code can be applied
        right now against subtotal_cents."""
        if not self.active:
            return 'This code is no longer active'
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return 'This code has expired'
        if self.max_redemptions is not None and self.redemption_count >= self.max_redemptions:
            return 'This code has reached its usage limit'
        if self.min_subtotal_cents is not None and subtotal_cents < self.min_subtotal_cents:
            return f'This code requires a subtotal of at least {self.min_subtotal_cents / 100:.2f}'
        return None

    def discount_for(self, subtotal_cents):
        """The discount in cents, capped so it can never exceed the
        subtotal (never a negative total)."""
        if self.discount_type == 'percent':
            raw = (subtotal_cents * self.amount) // 100
        else:
            raw = self.amount
        return max(0, min(raw, subtotal_cents))

    def __repr__(self):
        return f'PromoCode({self.id}) business={self.business_id} {self.code!r}'


class Order(db.Model):
    """One checkout -- one or more OrderItems. Customer is either a real
    User (customer_user_id) or a guest (guest_email/guest_phone +
    guest_manage_token), same no-account convention used across this
    session's other guest-facing work -- never a separate account system."""
    __tablename__ = 'order'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    payment_account_id = db.Column(db.Integer, db.ForeignKey('payment_account.id'), nullable=True)

    customer_user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True, index=True)
    guest_email = db.Column(db.String(150), nullable=True)
    guest_phone = db.Column(db.String(40), nullable=True)
    guest_manage_token = db.Column(db.String(64), nullable=True, unique=True, index=True)

    status = db.Column(db.String(20), nullable=False, default='pending', server_default='pending', index=True)

    subtotal_cents = db.Column(db.Integer, nullable=False)
    promo_code_id = db.Column(db.Integer, db.ForeignKey('promo_code.id', ondelete='SET NULL'), nullable=True)
    discount_cents = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    platform_fee_cents = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    total_cents = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), nullable=False, default='usd', server_default='usd')

    external_payment_id = db.Column(db.String(255), nullable=True, index=True)

    # Assigned once, the moment an order is first marked paid (see
    # routes/payments.py's _mark_order_paid) -- an Order already IS this
    # feature's payment ledger entry (customer identity, line items via
    # OrderItem, amount, paid status), so Phase 6 generates receipts
    # straight from it instead of duplicating all of that into a separate
    # Invoice table. NULL until paid; never reassigned after.
    invoice_number = db.Column(db.String(32), nullable=True, unique=True, index=True)

    # Set once a real Green Invoice document has been issued for this order
    # (see payments/green_invoice.py + routes/payments.py's
    # _mark_order_paid) -- NULL when the business has no enabled
    # GreenInvoiceAccount, or the call failed (never retried automatically;
    # the internal PDF invoice_number above always still works either way).
    green_invoice_doc_id = db.Column(db.String(64), nullable=True)
    green_invoice_pdf_url = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('orders', lazy=True, cascade='all, delete-orphan'))
    payment_account = db.relationship('PaymentAccount')
    customer = db.relationship('User', foreign_keys=[customer_user_id])
    promo_code = db.relationship('PromoCode')
    items = db.relationship('OrderItem', backref='order', lazy=True, cascade='all, delete-orphan')

    def __init__(self, business_id, subtotal_cents, total_cents, currency='usd',
                 customer_user_id=None, guest_email=None, guest_phone=None, guest_manage_token=None,
                 platform_fee_cents=0, payment_account_id=None, promo_code_id=None, discount_cents=0):
        self.business_id = business_id
        self.subtotal_cents = subtotal_cents
        self.total_cents = total_cents
        self.currency = currency
        self.customer_user_id = customer_user_id
        self.guest_email = guest_email
        self.guest_phone = guest_phone
        self.guest_manage_token = guest_manage_token
        self.platform_fee_cents = platform_fee_cents
        self.payment_account_id = payment_account_id
        self.promo_code_id = promo_code_id
        self.discount_cents = discount_cents

    @property
    def customer_label(self):
        if self.customer:
            return self.customer.email
        return self.guest_email or self.guest_phone or 'Unknown'

    def __repr__(self):
        return f'Order({self.id}) business={self.business_id} [{self.status}] {self.total_cents}{self.currency}'


class OrderItem(db.Model):
    __tablename__ = 'order_item'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id', ondelete='SET NULL'), nullable=True, index=True)

    # Snapshotted at purchase time -- never re-read Product's live row, so
    # a later price/name change never rewrites a past receipt.
    product_name = db.Column(db.String(150), nullable=False)
    unit_price_cents = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1, server_default='1')

    product = db.relationship('Product')

    def __init__(self, order_id, product_id, product_name, unit_price_cents, quantity=1):
        self.order_id = order_id
        self.product_id = product_id
        self.product_name = product_name
        self.unit_price_cents = unit_price_cents
        self.quantity = quantity

    @property
    def line_total_cents(self):
        return self.unit_price_cents * self.quantity

    def __repr__(self):
        return f'OrderItem({self.id}) order={self.order_id} {self.product_name!r} x{self.quantity}'
