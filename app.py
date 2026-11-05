"""
ShareLoop - Server, .org Domain Gatekeeper, Reactive Admin Analytics & Role-Based Routing (app.py)
---------------------------------------------------------------------------------------------------
Configures:
- Anti-Impersonation Organization Registration Check (`.endswith('.org')` -> `status='Pending'`)
- Student (`status='Active'`, required `dob`) vs. Organization (`status='Pending'`) registration lifecycle
- Strict Nepali 10-digit phone number validation (`(+977) 9848262163` or `9848262163`)
- Dynamic Role-Based Login Toggle gatekeeper (`Student` vs `Organization`, with `Admin` bypass)
- Dual-photo mandatory upload enforcement (Slot 1: Main Photo & Slot 2: Back / Side View)
- Admin Overview KPIs & Reactive Chart Aggregations (`GET /api/admin/overview`)
- Admin Resource Feed Management with Multi-Level Category Filtering & Delete (`GET /api/admin/resources`, `DELETE /api/items/<id>/delete`)
- Admin Read-Only Transactions Observer & Status Filtering (`GET /api/admin/transactions`)
- Separated Registered Accounts (`GET /api/admin/accounts/active` — excludes Admins & Pending/Rejected)
- Organization Approvals Queue (`GET /api/admin/accounts/pending` & `POST /api/admin/accounts/decision/<int:user_id>`)
"""

import os
import re
import uuid
import random
from datetime import datetime, timedelta, date
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from sqlalchemy import text
from werkzeug.utils import secure_filename
from models import (
    db,
    User,
    ResourceItem,
    ExchangeRequest,
    Message,
    FeedRequest,
    VALID_USER_ROLES,
    VALID_USER_STATUSES
)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'shareloop-production-secret-key-2026')

# ---------------------------------------------------------------------------
# Dynamic Local File Upload Storage Configuration
# ---------------------------------------------------------------------------
UPLOAD_SUBDIR = os.path.join('static', 'uploads')
UPLOAD_FOLDER = os.path.join(app.root_path, UPLOAD_SUBDIR)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max upload payload
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}

# ---------------------------------------------------------------------------
# Structured Multi-Level Category Taxonomy
# ---------------------------------------------------------------------------
CATEGORY_TAXONOMY = {
    'School Education': [
        'Primary (Class 1-5)',
        'Lower Secondary (Class 6-8)',
        'Secondary (9-10)',
        'Higher Secondary (Class 11-12)'
    ],
    'Higher Education': [
        'Science, Tech & Engineering (STEM)',
        'Business, Management & Economics',
        'Humanities, Arts & Social Sciences',
        'Medicine, Health & Life Sciences'
    ],
    'Equipment & Gear': [
        'Lab Gear & Equipment',
        'Stationeries & School Supplies'
    ],
    'Others': [
        'Others'
    ]
}

VALID_CATEGORIES = tuple(
    cat for group_list in CATEGORY_TAXONOMY.values() for cat in group_list
)

ORG_PENDING_REGISTRATION_MESSAGE = (
    'Account Created! Your registration is successful. Because you signed up as an “Organization”, '
    'our administrative team needs to verify your domain and details before you can access the dashboard. '
    'We will email you at your registered address as soon as your account is approved. This usually takes '
    'less than 24 hours. If you don\'t see our email within that time, please check your spam folder. '
    'For any further questions or information, feel free to reach out to us at support@shareloop.io or admin@shareloop.io.'
)

STUDENT_SUCCESS_REGISTRATION_MESSAGE = (
    'Registration successful! Your account has been created. You can now log in immediately.'
)


def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_image(file_storage, slot_prefix: str = 'resource') -> str | None:
    """
    Validates and saves an incoming FileStorage object into `static/uploads/`
    using `werkzeug.utils.secure_filename` and returns its public static path.
    """
    if not file_storage or not getattr(file_storage, 'filename', ''):
        return None

    original_name = secure_filename(file_storage.filename)
    if not original_name or not allowed_file(original_name):
        return None

    ext = original_name.rsplit('.', 1)[1].lower()
    unique_token = uuid.uuid4().hex[:10]
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    safe_slot = secure_filename(slot_prefix) or 'photo'
    final_filename = f"{safe_slot}_{timestamp}_{unique_token}.{ext}"

    destination = os.path.join(app.config['UPLOAD_FOLDER'], final_filename)
    file_storage.save(destination)
    return f"/static/uploads/{final_filename}"


def validate_password_strength(password: str) -> str | None:
    """
    Enforces server-side password policy:
    - Minimum length of 8 characters
    - At least one numeric character (0-9)
    - At least one special symbol character
    """
    if not password or len(password) < 8:
        return 'Password must be at least 8 characters long.'
    if not re.search(r'[0-9]', password):
        return 'Password must contain at least one numeric character (0-9).'
    if not re.search(r'[^A-Za-z0-9]', password):
        return 'Password must contain at least one special symbol (e.g. !@#$%^&*).'
    return None


NEPALI_PHONE_REGEX = re.compile(r'^(?:\(\+977\)\s*|\+977[\s\-]?)?([0-9]{10})$')


def validate_nepali_phone(phone_raw: str) -> tuple[bool, str]:
    """
    Enforces strict Nepali phone number format:
    Exactly 10 digits following an optional (+977) or +977 country code prefix
    (e.g., '(+977) 9848262163' or '9848262163').
    Returns (is_valid, normalized_phone_or_error).
    """
    cleaned = (phone_raw or '').strip()
    if not cleaned:
        return False, 'Phone number is required (e.g. (+977) 9848262163).'

    match = NEPALI_PHONE_REGEX.match(cleaned)
    if not match:
        return (
            False,
            'Invalid phone number. Please enter exactly 10 digits with optional (+977) prefix (e.g. (+977) 9848262163).'
        )

    ten_digits = match.group(1)
    return True, f"(+977) {ten_digits}"


def parse_dob_input(dob_raw: str) -> date | None:
    """
    Parses a Date of Birth string formatted as dd/mm/yyyy (or ISO yyyy-mm-dd).
    """
    cleaned = (dob_raw or '').strip()
    if not cleaned:
        return None

    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Database Connection Configuration (Reads strictly from .env / Environment)
# ---------------------------------------------------------------------------
def normalize_database_url(url: str) -> str:
    if not url:
        return 'sqlite:///shareloop.db'
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    return url


raw_db_url = normalize_database_url(os.environ.get('DATABASE_URL', ''))

app.config['SQLALCHEMY_DATABASE_URI'] = raw_db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
}

db.init_app(app)


# ---------------------------------------------------------------------------
# Authentication & Role-Based Access Control Decorators
# ---------------------------------------------------------------------------
def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    return db.session.get(User, user_id)


def api_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required. Please log in.'}), 401
        return f(user, *args, **kwargs)
    return decorated


def api_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required. Please log in.'}), 401
        if user.normalized_role != 'Admin':
            return jsonify({'error': 'Admin privileges required for this action.'}), 403
        return f(user, *args, **kwargs)
    return decorated


def api_student_required(f):
    """
    Role Access Isolation for the Student Request Feed:
    Strictly locks endpoints to accounts with role == 'Student'.
    Organizations and Admins are blocked from interacting with the feed.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required. Please log in.'}), 401
        if user.normalized_role != 'Student':
            return jsonify({
                'error': 'Access Denied: Only Student accounts can broadcast or respond to the Student Request Feed.'
            }), 403
        return f(user, *args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Session Initialization & Core Routing Engine
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    """
    Any unauthenticated request targeting the platform root instantly drops
    user views back to the unified authentication page (`login.html`).
    Authenticated browser states land inside the dynamic workspace (`index.html`).
    """
    user = get_current_user()
    if not user:
        return render_template('login.html')
    return render_template('index.html', current_user=user.to_dict())


@app.route('/login')
def login_page():
    user = get_current_user()
    if user:
        return redirect(url_for('index'))
    return render_template('login.html')


# ---------------------------------------------------------------------------
# Authentication & Profile API Endpoints
# ---------------------------------------------------------------------------
@app.route('/api/auth/register', methods=['POST'])
def api_register():
    """
    Registration API Pipeline:
    - Enforces 10-digit Nepali phone number format (`(+977) 9848262163`).
    - Student Accounts: Open email domain policy, requires Date of Birth (`dd/mm/yyyy`),
      sets `status='Active'`, and allows immediate login.
    - Organization Accounts: Anti-Impersonation check enforces that the email domain
      strictly ends with `.org` via `.endswith('.org')`. Saves record with
      `role='Organization'` and `status='Pending'` for administrative review.
    """
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    phone_raw = (data.get('phone') or '').strip()
    dob_raw = (data.get('dob') or '').strip()
    university = (data.get('university') or '').strip()
    role = (data.get('role') or 'Student').strip()
    password = data.get('password') or ''

    if not name or not email or not password:
        return jsonify({'error': 'Full name, email address, and password are required.'}), 400

    if '@' not in email or email.startswith('@') or email.endswith('@'):
        return jsonify({'error': 'Please provide a valid email address.'}), 400

    if role not in ('Student', 'Organization'):
        role = 'Student'

    # Anti-Impersonation Check:
    # - Student accounts have no domain restrictions.
    # - Organization accounts must strictly end with `.org`.
    extracted_domain = email.split('@', 1)[1].strip().lower()
    if role == 'Organization' and not extracted_domain.endswith('.org'):
        return jsonify({
            'error': 'Registration Rejected: Organizations must register using an official domain ending in .org'
        }), 400

    # Strict Nepali 10-digit phone number validation
    phone_ok, phone_result = validate_nepali_phone(phone_raw)
    if not phone_ok:
        return jsonify({'error': phone_result}), 400

    # Date of Birth validation (Required for Student accounts, omitted for Organizations)
    parsed_dob = None
    if role == 'Student':
        parsed_dob = parse_dob_input(dob_raw)
        if not parsed_dob:
            return jsonify({'error': 'Date of Birth is required for Student accounts in dd/mm/yyyy format.'}), 400

    pw_error = validate_password_strength(password)
    if pw_error:
        return jsonify({'error': pw_error}), 400

    existing = User.query.filter_by(email=email).first()
    if existing:
        return jsonify({'error': 'An account with this email is already registered.'}), 409

    # Pending Holding Vector: Organizations are held in 'Pending' status until Admin approval
    account_status = 'Pending' if role == 'Organization' else 'Active'

    new_user = User(
        name=name,
        email=email,
        phone=phone_result,
        role=role,
        dob=parsed_dob,
        status=account_status,
        university=university,
        completed_exchanges=0
    )
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()

    response_message = (
        ORG_PENDING_REGISTRATION_MESSAGE
        if role == 'Organization'
        else STUDENT_SUCCESS_REGISTRATION_MESSAGE
    )

    return jsonify({
        'message': response_message,
        'role': role,
        'status': account_status,
        'user': new_user.to_dict()
    }), 201


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    """
    Authenticates Student, Organization, and Admin credentials.
    Enforces:
    1. Dynamic Role-Based Login Toggle gatekeeper (`selected_role` must match user's role for Student/Organization).
    2. Organization `status == 'Pending'` or `status == 'Rejected'` verification block.
    """
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    selected_role = (data.get('selected_role') or data.get('role') or '').strip()

    if not email or not password:
        return jsonify({'error': 'Please enter both email and password.'}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({'error': 'Invalid email or password.'}), 401

    # Role Gatekeeper: Block Student login when 'Organization' is highlighted, and vice-versa
    if user.normalized_role in ('Student', 'Organization') and selected_role in ('Student', 'Organization'):
        if user.normalized_role != selected_role:
            return jsonify({
                'error': (
                    f"Access Denied: This account is registered as '{user.normalized_role}'. "
                    f"You cannot sign in while '{selected_role}' is selected under 'Login as a'."
                )
            }), 403

    # Block accounts whose approval status is still 'Pending'
    if user.normalized_status == 'Pending':
        return jsonify({
            'error': (
                'Account Pending Approval: Your Organization registration is currently awaiting administrative '
                'verification. We will email you as soon as your account is approved.'
            )
        }), 403

    # Block accounts whose approval status is 'Rejected'
    if user.normalized_status == 'Rejected':
        return jsonify({
            'error': 'Access Denied: Your account registration was cancelled or rejected by platform administration.'
        }), 403

    session['user_id'] = user.id
    return jsonify({
        'message': 'Logged in successfully.',
        'user': user.to_dict()
    })


@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    user = get_current_user()
    last_email = user.email if user else ''
    session.pop('user_id', None)
    return jsonify({
        'message': 'Logged out successfully.',
        'last_email': last_email
    })


@app.route('/api/auth/me', methods=['GET'])
@api_login_required
def api_me(current_user):
    return jsonify({'user': current_user.to_dict()})


@app.route('/api/profile/update', methods=['PUT'])
@api_login_required
def api_update_profile(current_user):
    """
    Allows updating Full Name, Primary Email Address, Phone Number (strict 10-digit Nepali format),
    and University/Organization Affiliation without injecting fallback defaults.
    """
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    phone_raw = (data.get('phone') or '').strip()
    university = (data.get('university') or '').strip()

    if not name:
        return jsonify({'error': 'Full name cannot be empty.'}), 400

    if not email or '@' not in email:
        return jsonify({'error': 'Primary email address cannot be empty.'}), 400

    phone_ok, phone_result = validate_nepali_phone(phone_raw)
    if not phone_ok:
        return jsonify({'error': phone_result}), 400

    if email != current_user.email:
        if current_user.normalized_role == 'Organization':
            new_domain = email.split('@', 1)[1].strip().lower()
            if not new_domain.endswith('.org'):
                return jsonify({
                    'error': 'Registration Rejected: Organizations must register using an official domain ending in .org'
                }), 400

        existing = User.query.filter(User.email == email, User.id != current_user.id).first()
        if existing:
            return jsonify({'error': 'That email address is already in use by another account.'}), 409
        current_user.email = email

    current_user.name = name
    current_user.phone = phone_result
    current_user.university = university

    db.session.commit()
    return jsonify({
        'message': 'Personal details updated successfully.',
        'user': current_user.to_dict()
    })


@app.route('/api/profile/password', methods=['PUT'])
@api_login_required
def api_change_password(current_user):
    data = request.get_json(silent=True) or {}
    current_password = data.get('current_password') or ''
    new_password = data.get('new_password') or ''

    if not current_user.check_password(current_password):
        return jsonify({'error': 'Current password is incorrect.'}), 400

    pw_error = validate_password_strength(new_password)
    if pw_error:
        return jsonify({'error': pw_error}), 400

    current_user.set_password(new_password)
    db.session.commit()
    return jsonify({'message': 'Password updated successfully.'})


@app.route('/api/profile/delete', methods=['DELETE'])
@api_login_required
def api_delete_account(current_user):
    db.session.delete(current_user)
    db.session.commit()
    session.pop('user_id', None)
    return jsonify({'message': 'Account deleted permanently.'})


# ---------------------------------------------------------------------------
# Resource Items & Dynamic Multi-Select Filtering + Multipart File Uploads
# ---------------------------------------------------------------------------
def apply_resource_item_filters(query, current_user, enforce_org_donate: bool = True):
    """
    Shared filtering helper for both student/organization `/api/items`
    and admin `/api/admin/resources`.
    """
    search = (request.args.get('search') or '').strip()
    if search:
        pattern = f'%{search}%'
        query = query.filter(
            db.or_(
                ResourceItem.title.ilike(pattern),
                ResourceItem.author.ilike(pattern),
                ResourceItem.course_code.ilike(pattern),
                ResourceItem.category.ilike(pattern)
            )
        )

    categories_param = (request.args.get('categories') or '').strip()
    if categories_param:
        categories = [c.strip() for c in categories_param.split('||') if c.strip()]
        if len(categories) == 1 and ',' in categories_param and '||' not in categories_param:
            if categories_param in VALID_CATEGORIES:
                categories = [categories_param]
            else:
                categories = [c.strip() for c in categories_param.split(',') if c.strip()]
        if categories:
            query = query.filter(ResourceItem.category.in_(categories))

    mine_only = request.args.get('mine_only', 'false').lower() == 'true'
    if enforce_org_donate and current_user.normalized_role == 'Organization' and not mine_only:
        query = query.filter(ResourceItem.exchange_type == 'Donate')
    else:
        exchange_param = (request.args.get('exchange_types') or '').strip()
        if exchange_param:
            exchange_types = [e.strip() for e in exchange_param.split(',') if e.strip()]
            if exchange_types:
                query = query.filter(ResourceItem.exchange_type.in_(exchange_types))

    conditions_param = (request.args.get('conditions') or '').strip()
    if conditions_param:
        conditions = [c.strip() for c in conditions_param.split(',') if c.strip()]
        if conditions:
            query = query.filter(ResourceItem.condition.in_(conditions))

    available_only = request.args.get('available_only', 'false').lower() == 'true'
    if available_only:
        query = query.filter(ResourceItem.is_available.is_(True))

    return query


@app.route('/api/items', methods=['GET'])
@api_login_required
def api_get_items(current_user):
    """
    Dynamically queries ResourceItems with multi-select filtering.
    When logged in as an 'Organization', enforces Exchange Type == 'Donate' only.
    """
    query = ResourceItem.query.filter(
        db.or_(ResourceItem.is_hidden.is_(False), ResourceItem.is_hidden.is_(None))
    )

    mine_only = request.args.get('mine_only', 'false').lower() == 'true'
    if mine_only:
        query = query.filter(ResourceItem.owner_id == current_user.id)

    query = apply_resource_item_filters(query, current_user, enforce_org_donate=True)
    items = query.order_by(ResourceItem.created_at.desc()).all()
    return jsonify({
        'items': [item.to_dict() for item in items],
        'total': len(items)
    })


@app.route('/api/items/<int:item_id>', methods=['GET'])
@api_login_required
def api_get_single_item(current_user, item_id):
    item = db.session.get(ResourceItem, item_id)
    if not item:
        return jsonify({'error': 'Resource item not found.'}), 404
    return jsonify({'item': item.to_dict()})


@app.route('/api/items/add-or-edit', methods=['POST'])
@api_login_required
def api_add_or_edit_item(current_user):
    """
    Accepts `multipart/form-data` (via JavaScript FormData) or JSON payloads.
    Organizations and Admins are restricted from publishing or editing item listings.
    Enforces Dual-Photo Mandatory Upload threshold: both Slot 1 ("1. Main Photo (Primary)")
    and Slot 2 ("2. Back / Side View") must be present.
    """
    if current_user.normalized_role == 'Organization':
        return jsonify({'error': 'Organizations operate to receive donations and cannot publish listings.'}), 403
    if current_user.normalized_role == 'Admin':
        return jsonify({'error': 'Administrators cannot create or edit resource listings.'}), 403

    if request.content_type and 'multipart/form-data' in request.content_type:
        data = request.form.to_dict()
    else:
        data = request.get_json(silent=True) or request.form.to_dict() or {}

    item_id = data.get('id')
    title = (data.get('title') or '').strip()
    author = (data.get('author') or '').strip()
    course_code = (data.get('course_code') or '').strip()
    category = (data.get('category') or '').strip()
    condition = (data.get('condition') or 'Good').strip()
    exchange_type = (data.get('exchange_type') or 'Lend').strip()
    description = (data.get('description') or '').strip()

    raw_avail = data.get('is_available', True)
    if isinstance(raw_avail, str):
        is_available = raw_avail.lower() in ('true', '1', 'yes', 'on')
    else:
        is_available = bool(raw_avail)

    if not title or not author or not category:
        return jsonify({'error': 'Title, Author/Manufacturer, and Category are required.'}), 400

    if category not in VALID_CATEGORIES:
        category = 'Others'

    uploaded_front = save_uploaded_image(request.files.get('front_cover'), 'main_photo')
    uploaded_back = save_uploaded_image(request.files.get('back_cover'), 'back_side_view')
    uploaded_spine = save_uploaded_image(request.files.get('spine'), 'detail_zoom')
    uploaded_inside = save_uploaded_image(request.files.get('inside_pages'), 'additional_view')

    extra_files = request.files.getlist('photos')
    for idx, extra_file in enumerate(extra_files):
        saved_extra = save_uploaded_image(extra_file, f'photo_{idx + 1}')
        if saved_extra:
            if not uploaded_front:
                uploaded_front = saved_extra
            elif not uploaded_back:
                uploaded_back = saved_extra
            elif not uploaded_spine:
                uploaded_spine = saved_extra
            elif not uploaded_inside:
                uploaded_inside = saved_extra

    if item_id and str(item_id).strip():
        item = db.session.get(ResourceItem, int(item_id))
        if not item:
            return jsonify({'error': 'Listing not found.'}), 404
        if item.owner_id != current_user.id:
            return jsonify({'error': 'You do not have permission to edit this listing.'}), 403

        final_front = uploaded_front or item.front_cover_path or item.image_url
        final_back = uploaded_back or item.back_cover_path
        if not final_front or not final_back:
            return jsonify({
                'error': 'Dual-Photo Requirement: Both Slot 1 (1. Main Photo) and Slot 2 (2. Back / Side View) are mandatory.'
            }), 400

        item.title = title
        item.author = author
        item.course_code = course_code
        item.category = category
        item.condition = condition
        item.exchange_type = exchange_type
        item.description = description
        item.is_available = is_available

        if uploaded_front:
            item.front_cover_path = uploaded_front
            item.image_url = uploaded_front
        if uploaded_back:
            item.back_cover_path = uploaded_back
        if uploaded_spine:
            item.spine_path = uploaded_spine
        if uploaded_inside:
            item.inside_pages_path = uploaded_inside

        db.session.commit()
        return jsonify({'message': 'Listing updated successfully.', 'item': item.to_dict()})

    if not uploaded_front or not uploaded_back:
        return jsonify({
            'error': 'Dual-Photo Requirement: Both Slot 1 (1. Main Photo) and Slot 2 (2. Back / Side View) are mandatory.'
        }), 400

    new_item = ResourceItem(
        title=title,
        author=author,
        course_code=course_code,
        category=category,
        condition=condition,
        exchange_type=exchange_type,
        description=description,
        image_url=uploaded_front,
        front_cover_path=uploaded_front,
        back_cover_path=uploaded_back,
        spine_path=uploaded_spine,
        inside_pages_path=uploaded_inside,
        is_available=is_available,
        is_hidden=False,
        owner_id=current_user.id
    )
    db.session.add(new_item)
    db.session.commit()
    return jsonify({'message': 'Resource published successfully!', 'item': new_item.to_dict()}), 201


@app.route('/api/items/<int:item_id>/delete', methods=['DELETE'])
@api_login_required
def api_delete_item(current_user, item_id):
    """
    Allows the listing owner or an Administrator to permanently delete a resource listing.
    """
    item = db.session.get(ResourceItem, item_id)
    if not item:
        return jsonify({'error': 'Item not found.'}), 404
    if item.owner_id != current_user.id and current_user.normalized_role != 'Admin':
        return jsonify({'error': 'Unauthorized.'}), 403

    db.session.delete(item)
    db.session.commit()
    return jsonify({'message': 'Listing removed from the platform.'})


# ---------------------------------------------------------------------------
# Exchange Requests & Messaging Endpoints
# ---------------------------------------------------------------------------
EXCHANGE_VERB_MAP = {
    'Donate': 'donating',
    'Lend': 'lending',
    'Swap': 'swapping'
}


@app.route('/api/requests', methods=['GET'])
@api_login_required
def api_get_requests(current_user):
    outgoing = ExchangeRequest.query.filter_by(requester_id=current_user.id).order_by(
        ExchangeRequest.created_at.desc()
    ).all()
    incoming = ExchangeRequest.query.filter_by(owner_id=current_user.id).order_by(
        ExchangeRequest.created_at.desc()
    ).all()

    return jsonify({
        'my_requests': [r.to_dict(include_messages=False) for r in outgoing],
        'incoming_requests': [r.to_dict(include_messages=False) for r in incoming]
    })


@app.route('/api/requests/create', methods=['POST'])
@api_login_required
def api_create_request(current_user):
    if current_user.normalized_role == 'Admin':
        return jsonify({'error': 'Administrators cannot create exchange requests.'}), 403

    data = request.get_json(silent=True) or {}
    item_id = data.get('item_id')
    notes = (data.get('notes') or '').strip()

    if not item_id:
        return jsonify({'error': 'item_id is required.'}), 400

    item = db.session.get(ResourceItem, int(item_id))
    if not item:
        return jsonify({'error': 'Resource item not found.'}), 404

    if item.owner_id == current_user.id:
        return jsonify({'error': 'You cannot request your own listing.'}), 400

    if not item.is_available:
        return jsonify({'error': 'This item is currently marked as unavailable.'}), 400

    if current_user.normalized_role == 'Organization' and item.exchange_type != 'Donate':
        return jsonify({'error': 'Organizations can only request items listed for donation.'}), 403

    existing = ExchangeRequest.query.filter(
        ExchangeRequest.item_id == item.id,
        ExchangeRequest.requester_id == current_user.id,
        ExchangeRequest.status.in_(['Pending', 'Accepted', 'Handover'])
    ).first()
    if existing:
        return jsonify({
            'message': 'You already have an active request for this item.',
            'request': existing.to_dict(include_messages=True)
        }), 200

    unique_code = f"#REQ-{random.randint(1000, 9999)}"
    while ExchangeRequest.query.filter_by(request_code=unique_code).first():
        unique_code = f"#REQ-{random.randint(1000, 9999)}"

    verb = EXCHANGE_VERB_MAP.get(item.exchange_type, 'exchanging')
    owner_name = item.owner.name if item.owner else 'Owner'
    auto_initial_chat_msg = (
        f"Hi {owner_name}! I just placed a request for '{item.title}'. "
        f"Let's coordinate our pickup time and location here."
    )

    if current_user.normalized_role == 'Organization':
        request_notes = f"Interested in {verb} '{item.title}'."
        first_message_text = auto_initial_chat_msg
    else:
        request_notes = notes or f"Interested in {verb} '{item.title}'."
        first_message_text = notes or auto_initial_chat_msg

    new_req = ExchangeRequest(
        request_code=unique_code,
        item_id=item.id,
        requester_id=current_user.id,
        owner_id=item.owner_id,
        status='Pending',
        notes=request_notes
    )
    db.session.add(new_req)
    db.session.flush()

    initial_msg = Message(
        request_id=new_req.id,
        sender_id=current_user.id,
        content=first_message_text
    )
    db.session.add(initial_msg)
    db.session.commit()

    return jsonify({
        'message': 'Exchange request submitted!',
        'request': new_req.to_dict(include_messages=True)
    }), 201


@app.route('/api/requests/<int:req_id>', methods=['GET'])
@api_login_required
def api_get_request_detail(current_user, req_id):
    req = db.session.get(ExchangeRequest, req_id)
    if not req:
        return jsonify({'error': 'Request not found.'}), 404

    if current_user.id not in (req.requester_id, req.owner_id) and current_user.normalized_role != 'Admin':
        return jsonify({'error': 'Access denied.'}), 403

    return jsonify({'request': req.to_dict(include_messages=True)})


@app.route('/api/requests/<int:req_id>/status', methods=['PUT', 'PATCH', 'POST'])
@api_login_required
def api_update_request_status(current_user, req_id):
    if current_user.normalized_role == 'Admin':
        return jsonify({'error': 'Administrators act as observers and cannot alter transaction statuses.'}), 403

    req = db.session.get(ExchangeRequest, req_id)
    if not req:
        return jsonify({'error': 'Request not found.'}), 404

    if current_user.id not in (req.requester_id, req.owner_id):
        return jsonify({'error': 'Access denied.'}), 403

    data = request.get_json(silent=True) or {}
    new_status = (data.get('status') or '').strip()
    valid_statuses = ['Pending', 'Accepted', 'Handover', 'Cancelled', 'Declined']

    if new_status not in valid_statuses:
        return jsonify({'error': f'Invalid status. Choose from {valid_statuses}.'}), 400

    if new_status in ['Accepted', 'Declined'] and current_user.id != req.owner_id:
        return jsonify({'error': 'Only the listing owner can accept or decline requests.'}), 403

    req.status = new_status
    req.updated_at = datetime.utcnow()

    if new_status == 'Accepted':
        sys_msg = Message(
            request_id=req.id,
            sender_id=current_user.id,
            content="Request accepted! Let's coordinate our pickup time and location here."
        )
        db.session.add(sys_msg)
    elif new_status == 'Cancelled':
        if req.feed_request_id:
            linked_feed = db.session.get(FeedRequest, req.feed_request_id)
            if linked_feed:
                linked_feed.is_active = True
        sys_msg = Message(
            request_id=req.id,
            sender_id=current_user.id,
            content="Transaction request has been cancelled."
        )
        db.session.add(sys_msg)
    elif new_status == 'Handover':
        if req.item:
            req.item.is_available = False
        if req.owner_user:
            req.owner_user.completed_exchanges = (req.owner_user.completed_exchanges or 0) + 1
        if req.requester:
            req.requester.completed_exchanges = (req.requester.completed_exchanges or 0) + 1
        sys_msg = Message(
            request_id=req.id,
            sender_id=current_user.id,
            content="Handover confirmed and completed! Thank you for using ShareLoop."
        )
        db.session.add(sys_msg)

    db.session.commit()
    return jsonify({
        'message': f'Request status updated to {new_status}.',
        'request': req.to_dict(include_messages=True)
    })


@app.route('/api/requests/<int:req_id>/cancel', methods=['POST', 'PUT'])
@api_login_required
def api_cancel_request(current_user, req_id):
    """
    Explicit Cancellation Endpoint for the original student requester (or participant):
    Closes out the transaction lifecycle row ('Cancelled'), restores linked FeedRequest
    state if applicable, and returns updated request state arrays.
    """
    if current_user.normalized_role == 'Admin':
        return jsonify({'error': 'Administrators act as observers and cannot cancel user transactions.'}), 403

    req = db.session.get(ExchangeRequest, req_id)
    if not req:
        return jsonify({'error': 'Request not found.'}), 404

    if current_user.id not in (req.requester_id, req.owner_id):
        return jsonify({'error': 'Access denied: Only the requester or owner can cancel this transaction.'}), 403

    req.status = 'Cancelled'
    req.updated_at = datetime.utcnow()

    if req.feed_request_id:
        linked_feed = db.session.get(FeedRequest, req.feed_request_id)
        if linked_feed:
            linked_feed.is_active = True

    cancel_msg = Message(
        request_id=req.id,
        sender_id=current_user.id,
        content="Request cancelled by the original requester."
    )
    db.session.add(cancel_msg)
    db.session.commit()

    outgoing = ExchangeRequest.query.filter_by(requester_id=current_user.id).order_by(
        ExchangeRequest.created_at.desc()
    ).all()
    incoming = ExchangeRequest.query.filter_by(owner_id=current_user.id).order_by(
        ExchangeRequest.created_at.desc()
    ).all()

    return jsonify({
        'message': 'Request cancelled and closed out.',
        'request': req.to_dict(include_messages=True),
        'my_requests': [r.to_dict(include_messages=False) for r in outgoing],
        'incoming_requests': [r.to_dict(include_messages=False) for r in incoming]
    })


@app.route('/api/requests/<int:req_id>/messages', methods=['POST'])
@api_login_required
def api_post_message(current_user, req_id):
    if current_user.normalized_role == 'Admin':
        return jsonify({'error': 'Administrators act as observers and cannot post messages in user transactions.'}), 403

    req = db.session.get(ExchangeRequest, req_id)
    if not req:
        return jsonify({'error': 'Request not found.'}), 404

    if current_user.id not in (req.requester_id, req.owner_id):
        return jsonify({'error': 'Access denied.'}), 403

    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'error': 'Message cannot be empty.'}), 400

    msg = Message(
        request_id=req.id,
        sender_id=current_user.id,
        content=content
    )
    db.session.add(msg)
    db.session.commit()

    return jsonify({
        'message': 'Message sent.',
        'chat_message': msg.to_dict(),
        'request': req.to_dict(include_messages=True)
    }), 201


# ---------------------------------------------------------------------------
# Student Request Feed System & Anti-Fraud Local Proof Upload Engine
# ---------------------------------------------------------------------------
@app.route('/api/feed/active', methods=['GET'])
@api_student_required
def api_get_active_feed(current_user):
    feed_posts = (
        FeedRequest.query.filter_by(is_active=True)
        .order_by(FeedRequest.created_at.desc())
        .all()
    )
    serialized = [post.to_dict() for post in feed_posts]
    return jsonify({
        'feed_requests': serialized,
        'items': serialized,
        'total': len(serialized)
    })


@app.route('/api/feed/create', methods=['POST'])
@api_student_required
def api_create_feed_request(current_user):
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    title = (data.get('title') or '').strip()
    category = (data.get('category') or '').strip()
    description = (data.get('description') or '').strip()

    if not title or not category:
        return jsonify({'error': 'Title and Category are required to broadcast a request.'}), 400

    if category not in VALID_CATEGORIES:
        category = 'Others'

    new_feed_req = FeedRequest(
        title=title,
        category=category,
        description=description,
        student_id=current_user.id,
        is_active=True
    )
    db.session.add(new_feed_req)
    db.session.commit()

    return jsonify({
        'message': 'Your request has been broadcast to the Student Request Feed!',
        'feed_request': new_feed_req.to_dict()
    }), 201


@app.route('/api/feed/respond/<int:feed_id>', methods=['POST'])
@api_student_required
def api_respond_to_feed_request(current_user, feed_id):
    feed_req = db.session.get(FeedRequest, feed_id)
    if not feed_req or not feed_req.is_active:
        return jsonify({'error': 'This student feed request is no longer active or was not found.'}), 404

    if feed_req.student_id == current_user.id:
        return jsonify({'error': 'You cannot respond to your own broadcast request.'}), 400

    if not request.content_type or 'multipart/form-data' not in request.content_type:
        return jsonify({
            'error': 'Anti-Fraud Verification: Responses must be submitted as multipart/form-data with local device photos.'
        }), 400

    form_data = request.form.to_dict()
    title = (form_data.get('title') or feed_req.title or '').strip()
    condition = (form_data.get('condition') or 'Good').strip()
    exchange_type = (form_data.get('exchange_type') or 'Lend').strip()
    author = (form_data.get('author') or f'Verified Peer Proof ({current_user.name})').strip()
    course_code = (form_data.get('course_code') or 'FEED').strip()
    description = (form_data.get('description') or f'Uploaded as direct physical proof for feed request: {feed_req.title}').strip()

    if not title:
        return jsonify({'error': 'Item Title is required.'}), 400

    uploaded_front = save_uploaded_image(request.files.get('front_cover'), 'feed_proof_main')
    uploaded_back = save_uploaded_image(request.files.get('back_cover'), 'feed_proof_back_side')
    uploaded_spine = save_uploaded_image(request.files.get('spine'), 'feed_proof_detail')
    uploaded_inside = save_uploaded_image(request.files.get('inside_pages'), 'feed_proof_additional')

    extra_files = request.files.getlist('photos')
    for idx, extra_file in enumerate(extra_files):
        saved_extra = save_uploaded_image(extra_file, f'feed_proof_{idx + 1}')
        if saved_extra:
            if not uploaded_front:
                uploaded_front = saved_extra
            elif not uploaded_back:
                uploaded_back = saved_extra
            elif not uploaded_spine:
                uploaded_spine = saved_extra
            elif not uploaded_inside:
                uploaded_inside = saved_extra

    if not uploaded_front or not uploaded_back:
        return jsonify({
            'error': 'Dual-Photo Requirement: Both Slot 1 (1. Main Photo) and Slot 2 (2. Back / Side View) proof photos are mandatory.'
        }), 400

    reserved_item = ResourceItem(
        title=title,
        author=author,
        course_code=course_code,
        category=feed_req.category if feed_req.category in VALID_CATEGORIES else 'Others',
        condition=condition,
        exchange_type=exchange_type,
        description=description,
        image_url=uploaded_front,
        front_cover_path=uploaded_front,
        back_cover_path=uploaded_back,
        spine_path=uploaded_spine,
        inside_pages_path=uploaded_inside,
        is_available=False,
        is_hidden=True,
        owner_id=current_user.id
    )
    db.session.add(reserved_item)
    db.session.flush()

    unique_code = f"#REQ-{random.randint(1000, 9999)}"
    while ExchangeRequest.query.filter_by(request_code=unique_code).first():
        unique_code = f"#REQ-{random.randint(1000, 9999)}"

    poster_user = db.session.get(User, feed_req.student_id)
    poster_name = poster_user.name if poster_user else 'Student'

    new_exchange_req = ExchangeRequest(
        request_code=unique_code,
        item_id=reserved_item.id,
        requester_id=feed_req.student_id,
        owner_id=current_user.id,
        feed_request_id=feed_req.id,
        status='Pending',
        notes=f"Direct response with device proof photos for feed request: '{feed_req.title}'."
    )
    db.session.add(new_exchange_req)
    db.session.flush()

    greeting_text = (
        f"Hi {poster_name}! I noticed your feed request. I physically have this item right here "
        f"and just uploaded proof photos from my device! Let's coordinate our pickup details here."
    )
    initial_msg = Message(
        request_id=new_exchange_req.id,
        sender_id=current_user.id,
        content=greeting_text
    )
    db.session.add(initial_msg)

    feed_req.is_active = False
    db.session.commit()

    return jsonify({
        'message': 'Proof photos verified! Redirecting to live pickup coordination chat...',
        'request': new_exchange_req.to_dict(include_messages=True),
        'item': reserved_item.to_dict()
    }), 201


# ---------------------------------------------------------------------------
# Dedicated Admin Portal API Endpoints (Role == 'Admin')
# ---------------------------------------------------------------------------
@app.route('/api/admin/overview', methods=['GET'])
@api_admin_required
def api_admin_overview(current_user):
    """
    Computes the 4 Core KPI Data Channels & 3 Interactive Chart Datasets:
    1. Total Platform Users: Active Students + Approved Organizations (`status == 'Active'`, excludes Admins).
    2. Resource Listings: Total sum of all published items on the platform.
    3. Exchange Transactions: Total sum of transactions where `status == 'Handover'`.
    4. Coordination Messages: Total sum of messages logged within requests that are in `'Accepted'` state.
    """
    all_users = User.query.order_by(User.created_at.desc()).all()
    published_items = (
        ResourceItem.query.filter(
            db.or_(ResourceItem.is_hidden.is_(False), ResourceItem.is_hidden.is_(None))
        )
        .order_by(ResourceItem.created_at.desc())
        .all()
    )
    all_requests = ExchangeRequest.query.order_by(ExchangeRequest.created_at.desc()).all()

    active_students = [
        u for u in all_users if u.normalized_role == 'Student' and u.normalized_status == 'Active'
    ]
    approved_orgs = [
        u for u in all_users if u.normalized_role == 'Organization' and u.normalized_status == 'Active'
    ]
    pending_orgs = [
        u for u in all_users if u.normalized_status == 'Pending'
    ]

    # 1. Total Platform Users = Active Students + Approved Organizations
    total_platform_users = len(active_students) + len(approved_orgs)

    # 2. Resource Listings = Total sum of published items
    total_resource_listings = len(published_items)
    active_resource_items = [i for i in published_items if i.is_available]

    # 3. Exchange Transactions = Total sum of transaction lifecycles where status == 'Handover'
    handover_transactions = [r for r in all_requests if r.status == 'Handover']
    exchange_transactions_count = len(handover_transactions)

    # 4. Coordination Messages = Total sum of messages logged within requests in 'Accepted' state
    accepted_messages_count = (
        db.session.query(Message)
        .join(ExchangeRequest, Message.request_id == ExchangeRequest.id)
        .filter(ExchangeRequest.status == 'Accepted')
        .count()
    )

    # -----------------------------------------------------------------------
    # Chart 1: "Exchanges Over Time" — Handovers per Week, Filterable by Month
    # -----------------------------------------------------------------------
    now = datetime.utcnow()
    month_buckets: dict[str, dict] = {}

    # Seed the last 3 calendar months so the dropdown always has selectable months
    for offset in range(0, 3):
        first_of_this_month = datetime(now.year, now.month, 1)
        target_dt = first_of_this_month - timedelta(days=offset * 28)
        m_key = target_dt.strftime('%Y-%m')
        m_label = target_dt.strftime('%B %Y')
        if m_key not in month_buckets:
            month_buckets[m_key] = {
                'key': m_key,
                'label': m_label,
                'weeks': [0, 0, 0, 0]
            }

    all_weeks_totals = [0, 0, 0, 0]
    for req in handover_transactions:
        ref_dt = req.updated_at or req.created_at or now
        m_key = ref_dt.strftime('%Y-%m')
        m_label = ref_dt.strftime('%B %Y')
        if m_key not in month_buckets:
            month_buckets[m_key] = {
                'key': m_key,
                'label': m_label,
                'weeks': [0, 0, 0, 0]
            }
        day = ref_dt.day
        week_idx = min(3, max(0, (day - 1) // 7))
        month_buckets[m_key]['weeks'][week_idx] += 1
        all_weeks_totals[week_idx] += 1

    sorted_months = sorted(month_buckets.values(), key=lambda x: x['key'], reverse=True)

    # -----------------------------------------------------------------------
    # Chart 2: "Exchange Types Breakdown" — Active Resource Listings by Type
    # -----------------------------------------------------------------------
    target_items_for_charts = active_resource_items if active_resource_items else published_items
    type_counts = {'Lend': 0, 'Donate': 0, 'Swap': 0}
    for item in target_items_for_charts:
        t = item.exchange_type if item.exchange_type in type_counts else 'Lend'
        type_counts[t] += 1

    # -----------------------------------------------------------------------
    # Chart 3: "Top Categories Shared" — Active Resource Listings by Category
    # -----------------------------------------------------------------------
    category_counts: dict[str, int] = {cat: 0 for cat in VALID_CATEGORIES}
    for item in target_items_for_charts:
        cat = item.category if item.category in category_counts else 'Others'
        category_counts[cat] = category_counts.get(cat, 0) + 1

    total_for_cats = max(1, len(target_items_for_charts))
    top_categories = [
        {
            'category': cat,
            'count': count,
            'percentage': round((count / total_for_cats) * 100, 1)
        }
        for cat, count in sorted(category_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        if count > 0
    ]

    return jsonify({
        'stats': {
            'total_platform_users': total_platform_users,
            'student_count': len(active_students),
            'organization_count': len(approved_orgs),
            'pending_accounts': len(pending_orgs),
            'resource_listings': total_resource_listings,
            'available_items': len(active_resource_items),
            'unavailable_items': total_resource_listings - len(active_resource_items),
            'exchange_transactions': exchange_transactions_count,
            'coordination_messages': accepted_messages_count,
            'total_requests': len(all_requests),
            'pending_requests': sum(1 for r in all_requests if r.status == 'Pending'),
            'accepted_requests': sum(1 for r in all_requests if r.status == 'Accepted'),
            'handover_requests': exchange_transactions_count
        },
        'charts': {
            'exchanges_over_time': {
                'week_labels': ['Week 1', 'Week 2', 'Week 3', 'Week 4'],
                'all_months_weeks': all_weeks_totals,
                'months': sorted_months
            },
            'exchange_types_breakdown': type_counts,
            'top_categories_shared': top_categories
        }
    })


@app.route('/api/admin/resources', methods=['GET'])
@api_admin_required
def api_admin_get_resources(current_user):
    """
    Admin Resource Feed endpoint with multi-level category, exchange type,
    condition, availability, and keyword filtering.
    """
    query = ResourceItem.query.filter(
        db.or_(ResourceItem.is_hidden.is_(False), ResourceItem.is_hidden.is_(None))
    )
    query = apply_resource_item_filters(query, current_user, enforce_org_donate=False)
    items = query.order_by(ResourceItem.created_at.desc()).all()
    serialized = [item.to_dict() for item in items]
    return jsonify({
        'resources': serialized,
        'items': serialized,
        'total': len(serialized)
    })


@app.route('/api/admin/transactions', methods=['GET'])
@api_admin_required
def api_admin_get_transactions(current_user):
    """
    Admin Read-Only Transactions endpoint with optional status filter
    ('Pending', 'Accepted', 'Handover', 'Cancelled').
    """
    query = ExchangeRequest.query
    status_filter = (request.args.get('status') or '').strip()
    if status_filter and status_filter != 'All':
        query = query.filter(ExchangeRequest.status == status_filter)

    transactions = query.order_by(ExchangeRequest.created_at.desc()).all()
    serialized = [req.to_dict(include_messages=False) for req in transactions]
    return jsonify({
        'transactions': serialized,
        'requests': serialized,
        'total': len(serialized)
    })


@app.route('/api/admin/accounts/active', methods=['GET'])
@api_admin_required
def api_admin_get_active_accounts(current_user):
    """
    The Registered Accounts Tab (`GET /api/admin/accounts/active`):
    Compiles and renders ONLY active platform participants (`status == 'Active'`)
    whose role is 'Student' or 'Organization'.
    Strictly filters out and hides any 'Admin' account or any 'Pending'/'Rejected' organization.
    Supports optional `?role=Student` or `?role=Organization` filtering alongside client-side role toggle isolation.
    """
    role_filter = (request.args.get('role') or '').strip()
    query = User.query.filter(
        User.status == 'Active',
        User.role.in_(['Student', 'Organization'])
    )
    if role_filter in ('Student', 'Organization'):
        query = query.filter(User.role == role_filter)

    active_users = query.order_by(User.created_at.desc()).all()
    serialized = [u.to_dict() for u in active_users]
    students_only = [u for u in serialized if u.get('role') == 'Student']
    organizations_only = [u for u in serialized if u.get('role') == 'Organization']
    return jsonify({
        'accounts': serialized,
        'users': serialized,
        'students': students_only,
        'organizations': organizations_only,
        'total': len(serialized)
    })


@app.route('/api/admin/accounts/pending', methods=['GET'])
@api_admin_required
def api_admin_get_pending_accounts(current_user):
    """
    The Organization Approvals Tab (`GET /api/admin/accounts/pending`):
    Displays only pending organization accounts waiting for evaluation (`status == 'Pending'`).
    """
    pending_users = (
        User.query.filter_by(status='Pending')
        .order_by(User.created_at.desc())
        .all()
    )
    serialized = [u.to_dict() for u in pending_users]
    return jsonify({
        'accounts': serialized,
        'users': serialized,
        'total': len(serialized)
    })


@app.route('/api/admin/accounts/decision/<int:user_id>', methods=['POST'])
@api_admin_required
def api_admin_account_decision(current_user, user_id):
    """
    Administrative Review Handler Endpoint (`POST /api/admin/accounts/decision/<int:user_id>`):
    - "Approve Account" ('Approve') sets status to 'Active'.
    - "Cancel Request" ('Reject' / 'Cancel') sets status to 'Rejected'.
    """
    target_user = db.session.get(User, user_id)
    if not target_user:
        return jsonify({'error': 'Account not found.'}), 404

    payload = request.get_json(silent=True)
    if isinstance(payload, str):
        raw_decision = payload.strip()
    elif isinstance(payload, dict):
        raw_decision = (
            payload.get('decision')
            or payload.get('action')
            or payload.get('status')
            or ''
        ).strip()
    else:
        raw_decision = (request.form.get('decision') or '').strip()

    normalized_decision = raw_decision.lower()
    if normalized_decision in ('approve', 'approve account', 'approved', 'active'):
        target_user.status = 'Active'
        action_label = 'Approved'
        msg_str = f"Organization account '{target_user.name}' ({target_user.email}) approved and activated."
    elif normalized_decision in ('reject', 'rejected', 'cancel', 'cancel request', 'cancelled', 'decline', 'declined'):
        target_user.status = 'Rejected'
        action_label = 'Cancelled'
        msg_str = f"Pending registration request for '{target_user.name}' ({target_user.email}) has been cancelled."
    else:
        return jsonify({
            'error': "Invalid decision payload. Expected 'Approve' or 'Reject'."
        }), 400

    db.session.commit()
    return jsonify({
        'message': msg_str,
        'decision': action_label,
        'status': target_user.status,
        'user': target_user.to_dict()
    })


# ---------------------------------------------------------------------------
# Automatic Schema Migration & Database Seeding on Launch
# ---------------------------------------------------------------------------
def ensure_schema_columns():
    alter_statements = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(30) NOT NULL DEFAULT 'Student'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS dob DATE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS status VARCHAR(30) NOT NULL DEFAULT 'Active'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS completed_exchanges INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ALTER COLUMN university DROP NOT NULL",
        "ALTER TABLE users ALTER COLUMN university SET DEFAULT ''",
        "UPDATE users SET completed_exchanges = exchange_count WHERE completed_exchanges = 0 AND exchange_count IS NOT NULL",
        "ALTER TABLE resource_items ADD COLUMN IF NOT EXISTS front_cover_path VARCHAR(500)",
        "ALTER TABLE resource_items ADD COLUMN IF NOT EXISTS back_cover_path VARCHAR(500)",
        "ALTER TABLE resource_items ADD COLUMN IF NOT EXISTS spine_path VARCHAR(500)",
        "ALTER TABLE resource_items ADD COLUMN IF NOT EXISTS inside_pages_path VARCHAR(500)",
        "ALTER TABLE resource_items ADD COLUMN IF NOT EXISTS is_hidden BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE exchange_requests ADD COLUMN IF NOT EXISTS feed_request_id INTEGER",
        "UPDATE resource_items SET category = 'Science, Tech & Engineering (STEM)' WHERE category IN ('Computer Science', 'Engineering')",
        "UPDATE resource_items SET category = 'Business, Management & Economics' WHERE category = 'Business & Economics'",
        "UPDATE resource_items SET category = 'Medicine, Health & Life Sciences' WHERE category = 'Medical & Life Sciences'",
        "UPDATE resource_items SET category = 'Primary (Class 1-5)' WHERE category = 'Children''s books'",
        "UPDATE feed_requests SET category = 'Science, Tech & Engineering (STEM)' WHERE category IN ('Computer Science', 'Engineering')",
        "UPDATE feed_requests SET category = 'Business, Management & Economics' WHERE category = 'Business & Economics'",
        "UPDATE feed_requests SET category = 'Medicine, Health & Life Sciences' WHERE category = 'Medical & Life Sciences'",
        "UPDATE feed_requests SET category = 'Primary (Class 1-5)' WHERE category = 'Children''s books'",
        "UPDATE resource_items SET back_cover_path = front_cover_path WHERE (back_cover_path IS NULL OR back_cover_path = '') AND front_cover_path IS NOT NULL",
        "UPDATE exchange_requests SET notes = REPLACE(notes, 'donateing', 'donating') WHERE notes LIKE '%donateing%'",
        "UPDATE exchange_requests SET notes = REPLACE(notes, 'donaeting', 'donating') WHERE notes LIKE '%donaeting%'",
    ]
    for stmt in alter_statements:
        try:
            db.session.execute(text(stmt))
            db.session.commit()
        except Exception:
            db.session.rollback()


def seed_sample_transactions():
    """
    Ensures sample Handover, Accepted, Pending, and Cancelled transactions exist
    so Admin KPI cards and the Exchanges Over Time chart have realistic data.
    """
    if ExchangeRequest.query.filter_by(status='Handover').count() > 0:
        return

    students = User.query.filter_by(role='Student', status='Active').all()
    items = ResourceItem.query.all()
    if len(students) < 2 or len(items) < 2:
        return

    now = datetime.utcnow()
    prev_month_dt = datetime(now.year, now.month, 1) - timedelta(days=12)

    sample_handovers = [
        ExchangeRequest(
            request_code='#REQ-7104',
            item_id=items[1 % len(items)].id,
            requester_id=students[0].id,
            owner_id=students[1].id,
            status='Handover',
            notes="Completed textbook handover outside the Engineering Library.",
            created_at=now - timedelta(days=10),
            updated_at=now - timedelta(days=9)
        ),
        ExchangeRequest(
            request_code='#REQ-7219',
            item_id=items[2 % len(items)].id,
            requester_id=students[1].id,
            owner_id=students[0].id,
            status='Handover',
            notes="Handed over Economics textbook for fall study group.",
            created_at=now - timedelta(days=3),
            updated_at=now - timedelta(days=2)
        ),
        ExchangeRequest(
            request_code='#REQ-6890',
            item_id=items[0].id,
            requester_id=students[-1].id,
            owner_id=students[0].id,
            status='Handover',
            notes="Previous month completed exchange.",
            created_at=prev_month_dt - timedelta(days=3),
            updated_at=prev_month_dt
        ),
        ExchangeRequest(
            request_code='#REQ-9012',
            item_id=items[-1].id,
            requester_id=students[0].id,
            owner_id=students[-1].id,
            status='Pending',
            notes="Interested in swapping lab kit this week.",
            created_at=now - timedelta(hours=14),
            updated_at=now - timedelta(hours=14)
        ),
        ExchangeRequest(
            request_code='#REQ-6540',
            item_id=items[0].id,
            requester_id=students[1].id,
            owner_id=students[-1].id,
            status='Cancelled',
            notes="Found another copy in the campus library.",
            created_at=now - timedelta(days=6),
            updated_at=now - timedelta(days=5)
        )
    ]

    for s_req in sample_handovers:
        if not ExchangeRequest.query.filter_by(request_code=s_req.request_code).first():
            db.session.add(s_req)
            db.session.flush()
            db.session.add(
                Message(
                    request_id=s_req.id,
                    sender_id=s_req.requester_id,
                    content=f"Hi! Coordinating pickup for {s_req.request_code}.",
                    created_at=s_req.created_at
                )
            )

    db.session.commit()


def seed_database():
    ensure_schema_columns()

    # Migrate any pre-existing legacy seeded student profiles on boot so existing databases update automatically
    legacy_student_migrations = [
        ('alex.morgan@university.edu', 'Rajesh KC', 'rajesh.kc@gmail.com', 'Tribhuvan University'),
        ('sarah.chen@stanford.edu', 'Rishi Dhamala', 'rishi.dhamala@gmail.com', 'Kathmandu University'),
        ('marcus.vance@stanford.edu', 'Bijay Shahi', 'bijay.shahi@gmail.com', 'Pokhara University'),
        ('elena.rostova@berkeley.edu', 'Shibu Pandey', 'shibu.pandey@gmail.com', 'Tribhuvan University'),
        ('devon.miller@ucla.edu', 'Ajay Devgan', 'ajay.devgan@gmail.com', 'Purbanchal University'),
    ]
    for old_email, new_name, new_email, new_uni in legacy_student_migrations:
        legacy_user = User.query.filter_by(email=old_email).first()
        if legacy_user:
            target_conflict = User.query.filter_by(email=new_email).first()
            if not target_conflict:
                legacy_user.name = new_name
                legacy_user.email = new_email
                legacy_user.university = new_uni
    db.session.commit()

    org_user = User.query.filter_by(email='org@shareloop.edu').first()
    if not org_user:
        org_user = User(
            name='Campus Book Bank Organization',
            email='org@shareloop.edu',
            phone='(+977) 9841234567',
            role='Organization',
            dob=None,
            status='Active',
            university='Campus Partner Network',
            completed_exchanges=24
        )
        org_user.set_password('password123')
        db.session.add(org_user)
    else:
        org_user.status = 'Active'

    verified_org = User.query.filter_by(email='contact@campusbank.org').first()
    if not verified_org:
        verified_org = User(
            name='Campus Book Bank Foundation',
            email='contact@campusbank.org',
            phone='(+977) 9841223344',
            role='Organization',
            dob=None,
            status='Active',
            university='Verified .org Partner',
            completed_exchanges=14
        )
        verified_org.set_password('password123!')
        db.session.add(verified_org)

    pending_org = User.query.filter_by(email='outreach@redcross.org').first()
    if not pending_org:
        pending_org = User(
            name='Youth Red Cross Society Nepal',
            email='outreach@redcross.org',
            phone='(+977) 9841998877',
            role='Organization',
            dob=None,
            status='Pending',
            university='Community Aid Partner',
            completed_exchanges=0
        )
        pending_org.set_password('password123!')
        db.session.add(pending_org)

    admin_user = User.query.filter_by(email='admin@shareloop.edu').first()
    if not admin_user:
        admin_user = User(
            name='Platform Administrator',
            email='admin@shareloop.edu',
            phone='(+977) 9851099999',
            role='Admin',
            dob=date(1992, 5, 14),
            status='Active',
            university='ShareLoop Moderation',
            completed_exchanges=42
        )
        admin_user.set_password('password123')
        db.session.add(admin_user)
    else:
        admin_user.status = 'Active'

    db.session.commit()

    existing_primary = ResourceItem.query.filter_by(category='Primary (Class 1-5)').first()
    if not existing_primary:
        first_owner = User.query.filter_by(role='Student').first()
        if first_owner:
            child_book = ResourceItem(
                title="The Little Prince & Illustrated Children's Treasury",
                author='Antoine de Saint-Exupéry',
                course_code='EDU 105',
                category='Primary (Class 1-5)',
                condition='New / Like New',
                exchange_type='Donate',
                description='Hardcover illustrated edition used for Early Childhood Education literacy practicum. Available as a free donation for students or partner organizations.',
                image_url='https://images.unsplash.com/photo-1512820790803-83ca734da794?auto=format&fit=crop&w=600&q=80',
                front_cover_path='https://images.unsplash.com/photo-1512820790803-83ca734da794?auto=format&fit=crop&w=600&q=80',
                back_cover_path='https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?auto=format&fit=crop&w=600&q=80',
                is_available=True,
                is_hidden=False,
                owner_id=first_owner.id
            )
            db.session.add(child_book)
            db.session.commit()

    if User.query.filter_by(role='Student').count() >= 3 and ResourceItem.query.count() > 1:
        if FeedRequest.query.count() == 0:
            seed_feed_requests()
        seed_sample_transactions()
        return

    print("Seeding ShareLoop relational database with initial users, items, and requests...")

    # 1. Rajesh KC (Initials: RK)
    rajesh = User.query.filter_by(email='rajesh.kc@gmail.com').first()
    if not rajesh:
        rajesh = User(
            name='Rajesh KC',
            email='rajesh.kc@gmail.com',
            phone='(+977) 9848262163',
            role='Student',
            dob=date(2002, 8, 19),
            status='Active',
            university='Tribhuvan University',
            completed_exchanges=12
        )
        rajesh.set_password('password123')
        db.session.add(rajesh)

    # 2. Rishi Dhamala (Initials: RD)
    rishi = User.query.filter_by(email='rishi.dhamala@gmail.com').first()
    if not rishi:
        rishi = User(
            name='Rishi Dhamala',
            email='rishi.dhamala@gmail.com',
            phone='(+977) 9841550192',
            role='Student',
            dob=date(2003, 3, 11),
            status='Active',
            university='Kathmandu University',
            completed_exchanges=18
        )
        rishi.set_password('password123')
        db.session.add(rishi)

    # 3. Bijay Shahi (Initials: BS)
    bijay = User.query.filter_by(email='bijay.shahi@gmail.com').first()
    if not bijay:
        bijay = User(
            name='Bijay Shahi',
            email='bijay.shahi@gmail.com',
            phone='(+977) 9841550144',
            role='Student',
            dob=date(2001, 11, 25),
            status='Active',
            university='Pokhara University',
            completed_exchanges=15
        )
        bijay.set_password('password123')
        db.session.add(bijay)

    # 4. Shibu Pandey (Initials: SP)
    shibu = User.query.filter_by(email='shibu.pandey@gmail.com').first()
    if not shibu:
        shibu = User(
            name='Shibu Pandey',
            email='shibu.pandey@gmail.com',
            phone='(+977) 9841550181',
            role='Student',
            dob=date(2002, 1, 30),
            status='Active',
            university='Tribhuvan University',
            completed_exchanges=9
        )
        shibu.set_password('password123')
        db.session.add(shibu)

    # 5. Ajay Devgan (Initials: AD)
    ajay = User.query.filter_by(email='ajay.devgan@gmail.com').first()
    if not ajay:
        ajay = User(
            name='Ajay Devgan',
            email='ajay.devgan@gmail.com',
            phone='(+977) 9841550177',
            role='Student',
            dob=date(2003, 7, 4),
            status='Active',
            university='Purbanchal University',
            completed_exchanges=6
        )
        ajay.set_password('password123')
        db.session.add(ajay)

    db.session.flush()

    if ResourceItem.query.count() <= 1:
        items = [
            ResourceItem(
                title='Operating System Concepts, 10th Edition',
                author='Abraham Silberschatz, Peter B. Galvin, Greg Gagne',
                course_code='CS 140',
                category='Science, Tech & Engineering (STEM)',
                condition='Good',
                exchange_type='Lend',
                description='Hardcover copy of the tenth edition of Operating System Concepts. Lightly used over one academic quarter.',
                image_url='https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?auto=format&fit=crop&w=600&q=80',
                front_cover_path='https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?auto=format&fit=crop&w=600&q=80',
                back_cover_path='https://images.unsplash.com/photo-1512820790803-83ca734da794?auto=format&fit=crop&w=600&q=80',
                is_available=True,
                is_hidden=False,
                owner_id=rishi.id
            ),
            ResourceItem(
                title='Introduction to Algorithms, 4th Edition (CLRS)',
                author='Thomas H. Cormen, Charles E. Leiserson, Ronald L. Rivest',
                course_code='CS 161',
                category='Science, Tech & Engineering (STEM)',
                condition='New / Like New',
                exchange_type='Lend',
                description='Pristine hardcover copy of CLRS 4th edition. Essential reference for Design and Analysis of Algorithms.',
                image_url='https://images.unsplash.com/photo-1512820790803-83ca734da794?auto=format&fit=crop&w=600&q=80',
                front_cover_path='https://images.unsplash.com/photo-1512820790803-83ca734da794?auto=format&fit=crop&w=600&q=80',
                back_cover_path='https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?auto=format&fit=crop&w=600&q=80',
                is_available=True,
                is_hidden=False,
                owner_id=bijay.id
            ),
            ResourceItem(
                title='Principles of Economics, 9th Edition',
                author='N. Gregory Mankiw',
                course_code='ECON 101',
                category='Business, Management & Economics',
                condition='Good',
                exchange_type='Donate',
                description='Complete macro and microeconomics textbook. Happy to donate to any student or campus organization.',
                image_url='https://images.unsplash.com/photo-1592496431122-2349e0fbc666?auto=format&fit=crop&w=600&q=80',
                front_cover_path='https://images.unsplash.com/photo-1592496431122-2349e0fbc666?auto=format&fit=crop&w=600&q=80',
                back_cover_path='https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?auto=format&fit=crop&w=600&q=80',
                is_available=True,
                is_hidden=False,
                owner_id=ajay.id
            ),
            ResourceItem(
                title='Calculus: Early Transcendentals, 8th Edition',
                author='James Stewart',
                course_code='MATH 51',
                category='Higher Secondary (Class 11-12)',
                condition='Fair',
                exchange_type='Donate',
                description='Covers single and multivariable calculus. Minor shelf wear on corners, all pages intact.',
                image_url='https://images.unsplash.com/photo-1509228468518-180dd4864904?auto=format&fit=crop&w=600&q=80',
                front_cover_path='https://images.unsplash.com/photo-1509228468518-180dd4864904?auto=format&fit=crop&w=600&q=80',
                back_cover_path='https://images.unsplash.com/photo-1512820790803-83ca734da794?auto=format&fit=crop&w=600&q=80',
                is_available=True,
                is_hidden=False,
                owner_id=shibu.id
            ),
            ResourceItem(
                title='Digital Oscilloscope & Breadboard Lab Kit',
                author='Tektronix / Arduino',
                course_code='EE 101A',
                category='Lab Gear & Equipment',
                condition='New / Like New',
                exchange_type='Lend',
                description='Complete portable USB oscilloscope, multimeter leads, and solderless breadboard jumper kit.',
                image_url='https://images.unsplash.com/photo-1532187863486-abf9dbad1b69?auto=format&fit=crop&w=600&q=80',
                front_cover_path='https://images.unsplash.com/photo-1532187863486-abf9dbad1b69?auto=format&fit=crop&w=600&q=80',
                back_cover_path='https://images.unsplash.com/photo-1532187863486-abf9dbad1b69?auto=format&fit=crop&w=600&q=80',
                is_available=True,
                is_hidden=False,
                owner_id=rajesh.id
            ),
            ResourceItem(
                title='Organic Chemistry, 8th Edition + Molecular Model Set',
                author='Paula Yurkanis Bruice',
                course_code='CHEM 33',
                category='Medicine, Health & Life Sciences',
                condition='Good',
                exchange_type='Swap',
                description='Includes both the 8th edition textbook and the 240-piece 3D organic stereochemistry molecular modeling kit.',
                image_url='https://images.unsplash.com/photo-1497633762265-9d179a990aa6?auto=format&fit=crop&w=600&q=80',
                front_cover_path='https://images.unsplash.com/photo-1497633762265-9d179a990aa6?auto=format&fit=crop&w=600&q=80',
                back_cover_path='https://images.unsplash.com/photo-1532187863486-abf9dbad1b69?auto=format&fit=crop&w=600&q=80',
                is_available=True,
                is_hidden=False,
                owner_id=rajesh.id
            )
        ]
        db.session.add_all(items)
        db.session.flush()

        now = datetime.utcnow()
        req1 = ExchangeRequest(
            request_code='#REQ-8492',
            item_id=items[0].id,
            requester_id=rajesh.id,
            owner_id=rishi.id,
            status='Accepted',
            notes="Interested in lending 'Operating System Concepts, 10th Edition'.",
            created_at=now - timedelta(days=2),
            updated_at=now - timedelta(days=1)
        )
        db.session.add(req1)
        db.session.flush()

        db.session.add_all([
            Message(
                request_id=req1.id,
                sender_id=rishi.id,
                content="Request accepted! Let's coordinate our pickup time and location here.",
                created_at=now - timedelta(hours=22)
            ),
            Message(
                request_id=req1.id,
                sender_id=rajesh.id,
                content='Hey Rishi, 3 PM outside the Central Library works perfectly! Thank you so much for lending this.',
                created_at=now - timedelta(hours=21, minutes=40)
            )
        ])

    db.session.commit()
    seed_feed_requests()
    seed_sample_transactions()
    print("Database seeding completed successfully.")


def seed_feed_requests():
    if FeedRequest.query.count() > 0:
        return
    rishi = User.query.filter_by(email='rishi.dhamala@gmail.com').first()
    bijay = User.query.filter_by(email='bijay.shahi@gmail.com').first()
    shibu = User.query.filter_by(email='shibu.pandey@gmail.com').first()

    sample_posts = []
    if rishi:
        sample_posts.append(
            FeedRequest(
                title='TI-84 Plus CE Graphing Calculator (for Midterm Exam)',
                category='Lab Gear & Equipment',
                description='Looking to borrow or swap for a TI-84 Plus CE graphing calculator for my Statistics midterm this Friday. Can meet anywhere near the Science Library!',
                student_id=rishi.id,
                is_active=True
            )
        )
    if bijay:
        sample_posts.append(
            FeedRequest(
                title='Computer Networking: A Top-Down Approach (8th Edition)',
                category='Science, Tech & Engineering (STEM)',
                description='Need Kurose & Ross 8th Edition for CS 144 problem sets. Happy to borrow for the term or swap with my Algorithms textbook.',
                student_id=bijay.id,
                is_active=True
            )
        )
    if shibu:
        sample_posts.append(
            FeedRequest(
                title='Lab Coat (Size M) & UV Safety Goggles',
                category='Medicine, Health & Life Sciences',
                description='Starting Organic Chemistry lab section next week and need a flame-resistant lab coat and splash goggles.',
                student_id=shibu.id,
                is_active=True
            )
        )
    if sample_posts:
        db.session.add_all(sample_posts)
        db.session.commit()


with app.app_context():
    db.create_all()
    seed_database()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print("==========================================================")
    print(f"ShareLoop Full-Stack Server running on http://127.0.0.1:{port}")
    print("Student Account      -> rajesh.kc@gmail.com        | password123")
    print("Organization Account -> org@shareloop.edu          | password123")
    print("Admin Account        -> admin@shareloop.edu        | password123")
    print("==========================================================")
    app.run(host='0.0.0.0', port=port, debug=True)
