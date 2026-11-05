"""
ShareLoop - Relational Database Layer (models.py)
-------------------------------------------------
Implements User (with strict 'Student', 'Organization', 'Admin' roles,
Date of Birth `dob`, approval `status` ['Active', 'Pending', 'Rejected'],
and `completed_exchanges` counter), ResourceItem (with 4-slot local file
upload paths and hidden/reserved flag), ExchangeRequest, Message, and
FeedRequest models.
"""

from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

VALID_USER_ROLES = ('Student', 'Organization', 'Admin')
VALID_USER_STATUSES = ('Active', 'Pending', 'Rejected')


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(40), nullable=True, default='')
    password_hash = db.Column(db.String(256), nullable=False)
    # Strict three-role access control: 'Student', 'Organization', or 'Admin'
    role = db.Column(db.String(30), nullable=False, default='Student', index=True)
    # Date of Birth (Required for Student registrations, omitted for Organizations)
    dob = db.Column(db.Date, nullable=True)
    # Approval lifecycle status: 'Active' for Students, 'Pending' -> 'Active'/'Rejected' for Organizations
    status = db.Column(db.String(30), nullable=False, default='Active', index=True)
    # Optional affiliation without hardcoded university fallbacks
    university = db.Column(db.String(140), nullable=True, default='')
    # Raw total completed exchanges count (no star ratings)
    completed_exchanges = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    items = db.relationship('ResourceItem', backref='owner', lazy=True, cascade='all, delete-orphan')
    feed_requests = db.relationship('FeedRequest', backref='student', lazy=True, cascade='all, delete-orphan')
    sent_requests = db.relationship(
        'ExchangeRequest',
        foreign_keys='ExchangeRequest.requester_id',
        backref='requester',
        lazy=True,
        cascade='all, delete-orphan'
    )
    received_requests = db.relationship(
        'ExchangeRequest',
        foreign_keys='ExchangeRequest.owner_id',
        backref='owner_user',
        lazy=True,
        cascade='all, delete-orphan'
    )
    messages_sent = db.relationship(
        'Message',
        foreign_keys='Message.sender_id',
        backref='sender',
        lazy=True,
        cascade='all, delete-orphan'
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def normalized_role(self) -> str:
        if self.role in VALID_USER_ROLES:
            return self.role
        return 'Student'

    @property
    def normalized_status(self) -> str:
        if self.status in VALID_USER_STATUSES:
            return self.status
        return 'Active'

    @property
    def email_domain(self) -> str:
        if self.email and '@' in self.email:
            return self.email.split('@', 1)[1].strip().lower()
        return ''

    @property
    def first_name(self) -> str:
        parts = [p for p in (self.name or '').strip().split() if p]
        return parts[0] if parts else 'Student'

    @property
    def initials(self) -> str:
        parts = [p for p in (self.name or '').strip().split() if p]
        if not parts:
            return 'U'
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()

    def to_dict(self) -> dict:
        dob_formatted = ''
        dob_iso = ''
        if isinstance(self.dob, date):
            dob_formatted = self.dob.strftime('%d/%m/%Y')
            dob_iso = self.dob.strftime('%Y-%m-%d')

        return {
            'id': self.id,
            'name': self.name,
            'first_name': self.first_name,
            'initials': self.initials,
            'email': self.email,
            'email_domain': self.email_domain,
            'phone': self.phone or '',
            'role': self.normalized_role,
            'dob': dob_formatted,
            'dob_iso': dob_iso,
            'status': self.normalized_status,
            'university': self.university if self.university is not None else '',
            'completed_exchanges': self.completed_exchanges or 0,
            'created_at': self.created_at.strftime('%b %d, %Y') if self.created_at else '',
            'registered_at': self.created_at.strftime('%b %d, %Y • %I:%M %p') if self.created_at else ''
        }


class ResourceItem(db.Model):
    __tablename__ = 'resource_items'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False, index=True)
    author = db.Column(db.String(200), nullable=False)
    course_code = db.Column(db.String(50), nullable=True, default='')
    category = db.Column(db.String(120), nullable=False, index=True)
    condition = db.Column(db.String(50), nullable=False, index=True)  # 'New / Like New', 'Good', 'Fair'
    exchange_type = db.Column(db.String(50), nullable=False, index=True)  # 'Lend', 'Donate', 'Swap'
    description = db.Column(db.Text, nullable=True)

    # Local File Upload Paths (4 slots: Slot 1 & Slot 2 mandatory)
    # 1. Main Photo (Primary) -> front_cover_path
    # 2. Back / Side View     -> back_cover_path
    # 3. Detail / Defect Zoom -> spine_path
    # 4. Additional View      -> inside_pages_path
    image_url = db.Column(db.String(500), nullable=True)
    front_cover_path = db.Column(db.String(500), nullable=True)
    back_cover_path = db.Column(db.String(500), nullable=True)
    spine_path = db.Column(db.String(500), nullable=True)
    inside_pages_path = db.Column(db.String(500), nullable=True)

    is_available = db.Column(db.Boolean, default=True, nullable=False, index=True)
    # Flags direct-response items created via the Request Feed so they remain hidden/reserved from Browse Exchange
    is_hidden = db.Column(db.Boolean, default=False, nullable=False, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    requests = db.relationship('ExchangeRequest', backref='item', lazy=True, cascade='all, delete-orphan')

    @property
    def primary_image(self) -> str:
        return (
            self.front_cover_path
            or self.image_url
            or self.back_cover_path
            or self.spine_path
            or self.inside_pages_path
            or 'https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?auto=format&fit=crop&w=600&q=80'
        )

    def to_dict(self) -> dict:
        pending_count = sum(1 for r in self.requests if r.status == 'Pending')
        return {
            'id': self.id,
            'title': self.title,
            'author': self.author,
            'course_code': self.course_code or 'GEN 101',
            'category': self.category,
            'condition': self.condition,
            'exchange_type': self.exchange_type,
            'description': self.description or '',
            'image_url': self.primary_image,
            'front_cover_path': self.front_cover_path or self.primary_image,
            'back_cover_path': self.back_cover_path or '',
            'spine_path': self.spine_path or '',
            'inside_pages_path': self.inside_pages_path or '',
            'photos': {
                'front_cover': self.front_cover_path or self.primary_image,
                'back_cover': self.back_cover_path or '',
                'spine': self.spine_path or '',
                'inside_pages': self.inside_pages_path or ''
            },
            'is_available': self.is_available,
            'is_hidden': bool(self.is_hidden),
            'owner_id': self.owner_id,
            'owner': self.owner.to_dict() if self.owner else None,
            'pending_requests_count': pending_count,
            'created_at': self.created_at.strftime('%b %d, %Y') if self.created_at else ''
        }


class ExchangeRequest(db.Model):
    __tablename__ = 'exchange_requests'

    id = db.Column(db.Integer, primary_key=True)
    request_code = db.Column(db.String(30), unique=True, nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey('resource_items.id', ondelete='CASCADE'), nullable=False, index=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    feed_request_id = db.Column(db.Integer, db.ForeignKey('feed_requests.id', ondelete='SET NULL'), nullable=True, index=True)
    # Valid statuses: 'Pending', 'Accepted', 'Handover', 'Cancelled', 'Declined'
    status = db.Column(db.String(30), nullable=False, default='Pending', index=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = db.relationship(
        'Message',
        backref='exchange_request',
        lazy=True,
        cascade='all, delete-orphan',
        order_by='Message.created_at.asc()'
    )

    def to_dict(self, include_messages: bool = True) -> dict:
        ref_dt = self.updated_at or self.created_at
        is_feed_tx = bool(self.feed_request_id or (self.item and self.item.is_hidden))
        return {
            'id': self.id,
            'request_code': self.request_code,
            'item_id': self.item_id,
            'item': self.item.to_dict() if self.item else None,
            'requester_id': self.requester_id,
            'requester': self.requester.to_dict() if self.requester else None,
            'owner_id': self.owner_id,
            'owner': self.owner_user.to_dict() if self.owner_user else None,
            'feed_request_id': self.feed_request_id,
            'is_feed_transaction': is_feed_tx,
            'status': self.status,
            'notes': self.notes or '',
            'created_at': self.created_at.strftime('%b %d, %Y') if self.created_at else '',
            'created_time': self.created_at.strftime('%b %d • %I:%M %p') if self.created_at else '',
            'updated_time': self.updated_at.strftime('%b %d • %I:%M %p') if self.updated_at else '',
            'month_key': ref_dt.strftime('%Y-%m') if ref_dt else '',
            'month_label': ref_dt.strftime('%B %Y') if ref_dt else '',
            'messages': [m.to_dict() for m in self.messages] if include_messages else []
        }


class Message(db.Model):
    __tablename__ = 'messages'

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('exchange_requests.id', ondelete='CASCADE'), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'request_id': self.request_id,
            'sender_id': self.sender_id,
            'sender_name': self.sender.name if self.sender else 'User',
            'sender_initials': self.sender.initials if self.sender else 'U',
            'content': self.content,
            'timestamp': self.created_at.strftime('%b %d, %I:%M %p') if self.created_at else ''
        }


class FeedRequest(db.Model):
    __tablename__ = 'feed_requests'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'title': self.title,
            'category': self.category,
            'description': self.description or '',
            'student_id': self.student_id,
            'student_name': self.student.name if self.student else 'Student',
            'student_first_name': self.student.first_name if self.student else 'Student',
            'student_initials': self.student.initials if self.student else 'ST',
            'student_university': self.student.university if (self.student and self.student.university) else '',
            'is_active': bool(self.is_active),
            'created_at': self.created_at.strftime('%b %d, %Y • %I:%M %p') if self.created_at else ''
        }
