from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import qrcode
import qrcode.image.svg
import os
import secrets
import io
import csv
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///meetings.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['QR_FOLDER'] = os.path.join('static', 'qrcodes')

db = SQLAlchemy(app)

# ─────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Meeting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    location = db.Column(db.String(200), default='')
    scheduled_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    token = db.Column(db.String(64), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    participants = db.relationship('Participant', backref='meeting', lazy=True, cascade='all, delete-orphan')

    @property
    def participant_count(self):
        return len(self.participants)


class Participant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey('meeting.id'), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50), default='')
    company = db.Column(db.String(200), default='')
    position = db.Column(db.String(200), default='')
    scanned_at = db.Column(db.DateTime, default=datetime.utcnow)


# ─────────────────────────────────────────
# AUTH DECORATOR
# ─────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'admin_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────

@app.route('/')
def index():
    if 'admin_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        admin = Admin.query.filter_by(username=username).first()
        if admin and admin.check_password(password):
            session['admin_id'] = admin.id
            session['admin_name'] = admin.username
            return redirect(url_for('dashboard'))
        flash('Identifiants incorrects.', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ─────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    meetings = Meeting.query.order_by(Meeting.scheduled_at.desc()).all()
    total_participants = Participant.query.count()
    active_meetings = Meeting.query.filter_by(is_active=True).count()
    inactive_meetings = Meeting.query.filter_by(is_active=False).count()

    # Stats par réunion pour le graphique
    meeting_stats = []
    for m in meetings[:10]:
        meeting_stats.append({
            'title': m.title[:25] + ('…' if len(m.title) > 25 else ''),
            'count': m.participant_count,
            'date': m.scheduled_at.strftime('%d/%m/%Y')
        })

    # Top entreprises
    from sqlalchemy import func
    top_companies = db.session.query(
        Participant.company,
        func.count(Participant.id).label('cnt')
    ).filter(Participant.company != '').group_by(Participant.company).order_by(func.count(Participant.id).desc()).limit(5).all()

    return render_template('dashboard.html',
        meetings=meetings,
        total_meetings=len(meetings),
        total_participants=total_participants,
        active_meetings=active_meetings,
        inactive_meetings=inactive_meetings,
        meeting_stats=meeting_stats,
        top_companies=top_companies
    )


# ─────────────────────────────────────────
# MEETINGS LIST + CRUD
# ─────────────────────────────────────────

@app.route('/meetings')
@login_required
def meetings_list():
    search = request.args.get('q', '').strip()
    status = request.args.get('status', '')  # 'active', 'closed', ou ''

    query = Meeting.query
    if search:
        query = query.filter(
            (Meeting.title.ilike(f'%{search}%')) |
            (Meeting.location.ilike(f'%{search}%')) |
            (Meeting.description.ilike(f'%{search}%'))
        )
    if status == 'active':
        query = query.filter_by(is_active=True)
    elif status == 'closed':
        query = query.filter_by(is_active=False)

    meetings = query.order_by(Meeting.scheduled_at.desc()).all()
    return render_template('meetings.html', meetings=meetings, search=search, status=status)


@app.route('/meetings/new', methods=['GET', 'POST'])
@login_required
def new_meeting():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        location = request.form.get('location', '').strip()
        scheduled_str = request.form.get('scheduled_at', '')

        if not title or not scheduled_str:
            flash('Le titre et la date sont obligatoires.', 'error')
            return render_template('meeting_form.html')

        try:
            scheduled_at = datetime.strptime(scheduled_str, '%Y-%m-%dT%H:%M')
        except ValueError:
            flash('Format de date invalide.', 'error')
            return render_template('meeting_form.html')

        token = secrets.token_urlsafe(32)
        meeting = Meeting(
            title=title,
            description=description,
            location=location,
            scheduled_at=scheduled_at,
            token=token
        )
        db.session.add(meeting)
        db.session.commit()

        flash(f'Réunion "{title}" créée avec succès !', 'success')
        return redirect(url_for('meeting_detail', meeting_id=meeting.id))

    return render_template('meeting_form.html')


@app.route('/meetings/<int:meeting_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_meeting(meeting_id):
    meeting = Meeting.query.get_or_404(meeting_id)
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        location = request.form.get('location', '').strip()
        scheduled_str = request.form.get('scheduled_at', '')

        if not title or not scheduled_str:
            flash('Le titre et la date sont obligatoires.', 'error')
            return render_template('meeting_form.html', meeting=meeting)

        try:
            scheduled_at = datetime.strptime(scheduled_str, '%Y-%m-%dT%H:%M')
        except ValueError:
            flash('Format de date invalide.', 'error')
            return render_template('meeting_form.html', meeting=meeting)

        meeting.title = title
        meeting.description = description
        meeting.location = location
        meeting.scheduled_at = scheduled_at
        db.session.commit()
        flash('Réunion mise à jour.', 'success')
        return redirect(url_for('meeting_detail', meeting_id=meeting.id))

    return render_template('meeting_form.html', meeting=meeting)


@app.route('/meetings/<int:meeting_id>')
@login_required
def meeting_detail(meeting_id):
    meeting = Meeting.query.get_or_404(meeting_id)
    participants = Participant.query.filter_by(meeting_id=meeting_id).order_by(Participant.scanned_at.desc()).all()
    base_url = request.host_url.rstrip('/')
    register_url = f"{base_url}/register/{meeting.token}"
    return render_template('meeting_detail.html', meeting=meeting, participants=participants, register_url=register_url)


@app.route('/meetings/<int:meeting_id>/toggle', methods=['POST'])
@login_required
def toggle_meeting(meeting_id):
    meeting = Meeting.query.get_or_404(meeting_id)
    meeting.is_active = not meeting.is_active
    db.session.commit()
    status = 'activée' if meeting.is_active else 'désactivée'
    flash(f'Réunion {status}.', 'success')
    return redirect(url_for('meeting_detail', meeting_id=meeting_id))


@app.route('/meetings/<int:meeting_id>/delete', methods=['POST'])
@login_required
def delete_meeting(meeting_id):
    meeting = Meeting.query.get_or_404(meeting_id)
    db.session.delete(meeting)
    db.session.commit()
    flash('Réunion supprimée.', 'success')
    return redirect(url_for('dashboard'))


def _fmt_phone(phone):
    """Préfixe tab pour forcer Excel à traiter comme texte (évite conversion numérique)."""
    s = (phone or '').strip()
    return f'\t{s}' if s else ''


def _fmt_dt(dt):
    """Formate une date en texte non-ambigu qu'Excel ne convertit pas automatiquement."""
    if not dt:
        return ''
    return dt.strftime('%d/%m/%Y à %Hh%M')


@app.route('/meetings/<int:meeting_id>/export')
@login_required
def export_participants(meeting_id):
    meeting = Meeting.query.get_or_404(meeting_id)
    participants = Participant.query.filter_by(meeting_id=meeting_id).all()

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(['Prénom', 'Nom', 'Email', 'Téléphone', 'Entreprise', 'Poste', 'Heure de scan'])
    for p in participants:
        writer.writerow([
            p.first_name or '',
            p.last_name or '',
            p.email or '',
            _fmt_phone(p.phone),
            p.company or '',
            p.position or '',
            _fmt_dt(p.scanned_at),
        ])

    output.seek(0)
    filename = f"participants_{meeting.title[:30].replace(' ', '_')}.csv"
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )


# ─────────────────────────────────────────
# PARTICIPANTS (vue globale)
# ─────────────────────────────────────────

@app.route('/participants')
@login_required
def all_participants():
    search = request.args.get('q', '').strip()
    query = Participant.query.join(Meeting)
    if search:
        query = query.filter(
            (Participant.first_name.ilike(f'%{search}%')) |
            (Participant.last_name.ilike(f'%{search}%')) |
            (Participant.email.ilike(f'%{search}%')) |
            (Participant.company.ilike(f'%{search}%'))
        )
    participants = query.order_by(Participant.scanned_at.desc()).all()
    return render_template('participants.html', participants=participants, search=search)


@app.route('/participants/export')
@login_required
def export_all_participants():
    search = request.args.get('q', '').strip()
    query = Participant.query.join(Meeting)
    if search:
        query = query.filter(
            (Participant.first_name.ilike(f'%{search}%')) |
            (Participant.last_name.ilike(f'%{search}%')) |
            (Participant.email.ilike(f'%{search}%')) |
            (Participant.company.ilike(f'%{search}%'))
        )
    participants = query.order_by(Participant.scanned_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(['Prénom', 'Nom', 'Email', 'Téléphone', 'Entreprise', 'Poste', 'Réunion', 'Date réunion', 'Heure de scan'])
    for p in participants:
        writer.writerow([
            p.first_name or '',
            p.last_name or '',
            p.email or '',
            _fmt_phone(p.phone),
            p.company or '',
            p.position or '',
            p.meeting.title,
            _fmt_dt(p.meeting.scheduled_at),
            _fmt_dt(p.scanned_at),
        ])

    output.seek(0)
    from datetime import date
    filename = f"tous_participants_{date.today().strftime('%Y%m%d')}.csv"
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )


@app.route('/participants/<int:participant_id>/delete', methods=['POST'])
@login_required
def delete_participant(participant_id):
    p = Participant.query.get_or_404(participant_id)
    meeting_id = p.meeting_id
    db.session.delete(p)
    db.session.commit()
    flash('Participant supprimé.', 'success')
    return redirect(request.referrer or url_for('meeting_detail', meeting_id=meeting_id))


# ─────────────────────────────────────────
# FORMULAIRE PUBLIC (scan QR)
# ─────────────────────────────────────────

@app.route('/register/<token>', methods=['GET', 'POST'])
def register(token):
    meeting = Meeting.query.filter_by(token=token).first_or_404()

    if not meeting.is_active:
        return render_template('register_closed.html', meeting=meeting)

    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip().title()
        last_name = request.form.get('last_name', '').strip().title()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        company = request.form.get('company', '').strip()
        position = request.form.get('position', '').strip()

        if not first_name or not last_name or not email:
            flash('Prénom, nom et email sont obligatoires.', 'error')
            return render_template('register.html', meeting=meeting)

        # Anti-doublon : même email dans la même réunion (insensible à la casse)
        existing = Participant.query.filter_by(
            meeting_id=meeting.id,
            email=email
        ).first()

        if existing:
            return render_template('register_duplicate.html', meeting=meeting, participant=existing)

        participant = Participant(
            meeting_id=meeting.id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            company=company,
            position=position,
            scanned_at=datetime.now()
        )
        db.session.add(participant)
        db.session.commit()

        return render_template('register_success.html', meeting=meeting, participant=participant)

    return render_template('register.html', meeting=meeting)


# ─────────────────────────────────────────
# STATS API (pour graphiques)
# ─────────────────────────────────────────

@app.route('/api/stats')
@login_required
def api_stats():
    from sqlalchemy import func
    daily = db.session.query(
        func.date(Participant.scanned_at).label('day'),
        func.count(Participant.id).label('cnt')
    ).group_by(func.date(Participant.scanned_at)).order_by('day').limit(30).all()
    return jsonify({
        'daily': [{'date': str(r.day), 'count': r.cnt} for r in daily]
    })


@app.route('/api/dashboard-stats')
@login_required
def api_dashboard_stats():
    total_participants = Participant.query.count()
    total_meetings = Meeting.query.count()
    active_meetings = Meeting.query.filter_by(is_active=True).count()
    inactive_meetings = Meeting.query.filter_by(is_active=False).count()
    avg = round(total_participants / total_meetings, 1) if total_meetings > 0 else 0

    meetings = Meeting.query.order_by(Meeting.scheduled_at.desc()).limit(10).all()
    meeting_stats = [{
        'id': m.id,
        'title': m.title[:25] + ('…' if len(m.title) > 25 else ''),
        'count': m.participant_count,
    } for m in meetings]

    return jsonify({
        'total_participants': total_participants,
        'total_meetings': total_meetings,
        'active_meetings': active_meetings,
        'inactive_meetings': inactive_meetings,
        'avg_participants': avg,
        'meeting_stats': meeting_stats,
    })


# ─────────────────────────────────────────
# QR CODE — génération dynamique
# ─────────────────────────────────────────

def _make_qr_bytes(url):
    """Génère un QR code en mémoire à partir d'une URL et retourne les bytes PNG."""
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1a1a2e", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


@app.route('/meetings/<int:meeting_id>/qr.png')
@login_required
def meeting_qr_image(meeting_id):
    """Sert le QR code comme image inline (utilisé dans <img src>)."""
    meeting = Meeting.query.get_or_404(meeting_id)
    base_url = request.host_url.rstrip('/')
    url = f"{base_url}/register/{meeting.token}"
    return send_file(_make_qr_bytes(url), mimetype='image/png')


@app.route('/meetings/<int:meeting_id>/qr')
@login_required
def download_qr(meeting_id):
    """Télécharge le QR code en PNG."""
    meeting = Meeting.query.get_or_404(meeting_id)
    base_url = request.host_url.rstrip('/')
    url = f"{base_url}/register/{meeting.token}"
    return send_file(
        _make_qr_bytes(url),
        mimetype='image/png',
        as_attachment=True,
        download_name=f'qr_{meeting.title[:30]}.png'
    )


# ─────────────────────────────────────────
# INIT DB
# ─────────────────────────────────────────

def init_db():
    with app.app_context():
        db.create_all()
        if not Admin.query.first():
            admin = Admin(username='admin')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("✅ Admin créé → username: admin | password: admin123")
            print("⚠️  Changez le mot de passe en production !")


if __name__ == '__main__':
    os.makedirs(app.config['QR_FOLDER'], exist_ok=True)
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
