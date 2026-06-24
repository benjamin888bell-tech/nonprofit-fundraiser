from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date
import os
import base64

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "nonprofit-secret-key-change-in-prod")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///nonprofit.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB photo limit

db = SQLAlchemy(app)


# ─── Models ───────────────────────────────────────────────────────────────────

CAMPAIGN_CATEGORIES = [
    "Operations & Maintenance",
    "Social Programs",
]

CATEGORY_ICONS = {
    "Operations & Maintenance": "🔧",
    "Social Programs": "🤝",
}

class Campaign(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100), default="Operations & Maintenance")
    description = db.Column(db.Text)
    goal = db.Column(db.Float, nullable=False)
    photo = db.Column(db.Text)             # base64-encoded uploaded image
    photo_mime = db.Column(db.String(50))  # e.g. "image/jpeg"
    photo_url = db.Column(db.String(500))  # fallback URL for sample/external photos
    start_date = db.Column(db.Date, default=date.today)
    end_date = db.Column(db.Date)
    active = db.Column(db.Boolean, default=True)
    donations = db.relationship("Donation", backref="campaign", lazy=True)

    @property
    def total_raised(self):
        return sum(d.amount for d in self.donations)

    @property
    def progress_pct(self):
        if self.goal == 0:
            return 0
        return min(round(self.total_raised / self.goal * 100, 1), 100)

    @property
    def donor_count(self):
        return len(set(d.donor_id for d in self.donations if d.donor_id))

    @property
    def photo_src(self):
        # Prefer uploaded photo; fall back to URL
        if self.photo and self.photo_mime:
            return f"data:{self.photo_mime};base64,{self.photo}"
        return self.photo_url or None


class Donor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200))
    phone = db.Column(db.String(50))
    notes = db.Column(db.Text)
    photo = db.Column(db.Text)            # base64-encoded uploaded photo
    photo_mime = db.Column(db.String(50)) # e.g. "image/jpeg"
    photo_url = db.Column(db.String(500)) # fallback URL for sample/external photos
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    donations = db.relationship("Donation", backref="donor", lazy=True)

    @property
    def total_given(self):
        return sum(d.amount for d in self.donations)

    @property
    def photo_src(self):
        if self.photo and self.photo_mime:
            return f"data:{self.photo_mime};base64,{self.photo}"
        return self.photo_url or None


class Donation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, default=date.today)
    note = db.Column(db.String(300))
    donor_id = db.Column(db.Integer, db.ForeignKey("donor.id"), nullable=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaign.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def save_photo(campaign, file):
    """Read uploaded file and store as base64 on the campaign object."""
    if file and file.filename:
        data = file.read()
        mime = file.content_type or "image/jpeg"
        campaign.photo = base64.b64encode(data).decode("utf-8")
        campaign.photo_mime = mime


def save_donor_photo(donor, file):
    """Read uploaded file and store as base64 on the donor object."""
    if file and file.filename:
        data = file.read()
        mime = file.content_type or "image/jpeg"
        donor.photo = base64.b64encode(data).decode("utf-8")
        donor.photo_mime = mime


# ─── Admin Routes ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    campaigns = Campaign.query.filter_by(active=True).all()
    total_raised = sum(c.total_raised for c in Campaign.query.all())
    total_donors = Donor.query.count()
    total_donations = Donation.query.count()
    recent_donations = (
        Donation.query
        .order_by(Donation.created_at.desc())
        .limit(5)
        .all()
    )
    return render_template(
        "admin_dashboard.html",
        campaigns=campaigns,
        total_raised=total_raised,
        total_donors=total_donors,
        total_donations=total_donations,
        recent_donations=recent_donations,
        categories=CAMPAIGN_CATEGORIES,
        category_icons=CATEGORY_ICONS,
    )


# Campaigns
@app.route("/campaigns")
def campaigns():
    all_campaigns = Campaign.query.order_by(Campaign.category, Campaign.start_date.desc()).all()
    has_samples = any('[SAMPLE]' in c.name for c in all_campaigns)
    return render_template("admin_campaigns.html", campaigns=all_campaigns, categories=CAMPAIGN_CATEGORIES, category_icons=CATEGORY_ICONS, has_samples=has_samples)


@app.route("/campaigns/new", methods=["GET", "POST"])
def new_campaign():
    if request.method == "POST":
        end_str = request.form.get("end_date")
        campaign = Campaign(
            name=request.form["name"],
            category=request.form.get("category", "Operations & Maintenance"),
            description=request.form.get("description"),
            goal=float(request.form["goal"]),
            start_date=date.fromisoformat(request.form["start_date"]),
            end_date=date.fromisoformat(end_str) if end_str else None,
        )
        save_photo(campaign, request.files.get("photo"))
        db.session.add(campaign)
        db.session.commit()
        flash("Campaign created!", "success")
        return redirect(url_for("campaigns"))
    return render_template("admin_campaign_form.html", campaign=None, categories=CAMPAIGN_CATEGORIES)


@app.route("/campaigns/<int:id>/edit", methods=["GET", "POST"])
def edit_campaign(id):
    campaign = Campaign.query.get_or_404(id)
    if request.method == "POST":
        end_str = request.form.get("end_date")
        campaign.name = request.form["name"]
        campaign.category = request.form.get("category", "Operations & Maintenance")
        campaign.description = request.form.get("description")
        campaign.goal = float(request.form["goal"])
        campaign.start_date = date.fromisoformat(request.form["start_date"])
        campaign.end_date = date.fromisoformat(end_str) if end_str else None
        campaign.active = "active" in request.form
        photo_file = request.files.get("photo")
        if photo_file and photo_file.filename:
            save_photo(campaign, photo_file)
        db.session.commit()
        flash("Campaign updated!", "success")
        return redirect(url_for("campaigns"))
    return render_template("admin_campaign_form.html", campaign=campaign, categories=CAMPAIGN_CATEGORIES)


@app.route("/campaigns/<int:id>/delete", methods=["POST"])
def delete_campaign(id):
    campaign = Campaign.query.get_or_404(id)
    db.session.delete(campaign)
    db.session.commit()
    flash("Campaign deleted.", "info")
    return redirect(url_for("campaigns"))


# Donors
@app.route("/donors")
def donors():
    all_donors = Donor.query.order_by(Donor.name).all()
    return render_template("admin_donors.html", donors=all_donors)


@app.route("/donors/new", methods=["GET", "POST"])
def new_donor():
    if request.method == "POST":
        donor = Donor(
            name=request.form["name"],
            email=request.form.get("email"),
            phone=request.form.get("phone"),
            notes=request.form.get("notes"),
        )
        save_donor_photo(donor, request.files.get("photo"))
        db.session.add(donor)
        db.session.commit()
        flash("Donor added!", "success")
        return redirect(url_for("donors"))
    return render_template("admin_donor_form.html", donor=None)


@app.route("/donors/<int:id>/edit", methods=["GET", "POST"])
def edit_donor(id):
    donor = Donor.query.get_or_404(id)
    if request.method == "POST":
        donor.name = request.form["name"]
        donor.email = request.form.get("email")
        donor.phone = request.form.get("phone")
        donor.notes = request.form.get("notes")
        photo_file = request.files.get("photo")
        if photo_file and photo_file.filename:
            save_donor_photo(donor, photo_file)
        db.session.commit()
        flash("Donor updated!", "success")
        return redirect(url_for("donors"))
    return render_template("admin_donor_form.html", donor=donor)


# Donations
@app.route("/donations")
def donations():
    all_donations = Donation.query.order_by(Donation.date.desc()).all()
    return render_template("admin_donations.html", donations=all_donations)


@app.route("/donations/new", methods=["GET", "POST"])
def new_donation():
    campaigns = Campaign.query.filter_by(active=True).all()
    donors = Donor.query.order_by(Donor.name).all()
    if request.method == "POST":
        donor_id = request.form.get("donor_id") or None
        donation = Donation(
            amount=float(request.form["amount"]),
            date=date.fromisoformat(request.form["date"]),
            note=request.form.get("note"),
            donor_id=int(donor_id) if donor_id else None,
            campaign_id=int(request.form["campaign_id"]),
        )
        db.session.add(donation)
        db.session.commit()
        flash("Donation logged!", "success")
        return redirect(url_for("donations"))
    return render_template("admin_donation_form.html", campaigns=campaigns, donors=donors, today=date.today().isoformat())


# Reports
@app.route("/reports")
def reports():
    campaigns = Campaign.query.all()
    monthly = db.session.execute(
        db.text(
            "SELECT strftime('%Y-%m', date) as month, SUM(amount) as total "
            "FROM donation GROUP BY month ORDER BY month DESC LIMIT 12"
        )
    ).fetchall()
    monthly = list(reversed(monthly))
    top_donors = db.session.execute(
        db.text(
            "SELECT donor_id, SUM(amount) as total FROM donation "
            "WHERE donor_id IS NOT NULL GROUP BY donor_id ORDER BY total DESC LIMIT 10"
        )
    ).fetchall()
    top_donors_data = []
    for row in top_donors:
        donor = Donor.query.get(row[0])
        if donor:
            top_donors_data.append({"name": donor.name, "total": row[1]})

    return render_template(
        "admin_reports.html",
        campaigns=campaigns,
        monthly=monthly,
        top_donors=top_donors_data,
    )


# API for charts
@app.route("/api/campaigns")
def api_campaigns():
    campaigns = Campaign.query.all()
    return jsonify([
        {
            "id": c.id,
            "name": c.name,
            "category": c.category,
            "goal": c.goal,
            "raised": c.total_raised,
            "progress": c.progress_pct,
            "donors": c.donor_count,
            "active": c.active,
            "description": c.description,
        }
        for c in campaigns
    ])


# ─── Public Website Routes ────────────────────────────────────────────────────

@app.route("/public")
def public_home():
    campaigns = Campaign.query.filter_by(active=True).order_by(Campaign.category, Campaign.start_date.desc()).all()
    total_raised = sum(c.total_raised for c in campaigns)
    ops = [c for c in campaigns if c.category == "Operations & Maintenance"]
    social = [c for c in campaigns if c.category == "Social Programs"]
    return render_template(
        "public_home.html",
        campaigns=campaigns,
        ops_campaigns=ops,
        social_campaigns=social,
        total_raised=total_raised,
        category_icons=CATEGORY_ICONS,
    )


@app.route("/public/campaign/<int:id>")
def public_campaign(id):
    campaign = Campaign.query.get_or_404(id)
    recent = (
        Donation.query
        .filter_by(campaign_id=id)
        .order_by(Donation.date.desc())
        .limit(10)
        .all()
    )
    # Group donations by donor for bubble sizing
    donor_map = {}
    for d in campaign.donations:
        key = d.donor_id if d.donor_id else f"anon_{d.id}"
        if key not in donor_map:
            donor_map[key] = {
                "name": d.donor.name if d.donor else "Anonymous",
                "total": 0,
                "photo": d.donor.photo_src if d.donor else None,
            }
        donor_map[key]["total"] += d.amount
    bubble_data = sorted(donor_map.values(), key=lambda x: x["total"], reverse=True)
    return render_template("public_campaign.html", campaign=campaign, recent=recent, bubble_data=bubble_data)


# ─── Seed & Init ─────────────────────────────────────────────────────────────

def seed_data():
    if Campaign.query.count() > 0:
        return
    campaigns = [
        Campaign(
            name="[SAMPLE] Building Maintenance Fund",
            category="Operations & Maintenance",
            description="Keep our facilities safe and well-maintained for everyone who uses them.",
            goal=50000,
            photo_url="https://images.unsplash.com/photo-1504307651254-35680f356dfd?w=800&h=400&fit=crop",
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        ),
        Campaign(
            name="[SAMPLE] New Community Center Roof",
            category="Operations & Maintenance",
            description="Replace the aging roof on our main community center building.",
            goal=80000,
            photo_url="https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=800&h=400&fit=crop",
            start_date=date(2026, 3, 1), end_date=date(2026, 9, 30),
        ),
        Campaign(
            name="[SAMPLE] Youth Scholarship Fund",
            category="Social Programs",
            description="Provide college scholarships to 10 deserving local students.",
            goal=30000,
            photo_url="https://images.unsplash.com/photo-1503676260728-1c00da094a0b?w=800&h=400&fit=crop",
            start_date=date(2026, 2, 1), end_date=date(2026, 6, 30),
        ),
        Campaign(
            name="[SAMPLE] Senior Meals Program",
            category="Social Programs",
            description="Deliver hot meals to homebound seniors in our community five days a week.",
            goal=25000,
            photo_url="https://images.unsplash.com/photo-1547592166-23ac45744acd?w=800&h=400&fit=crop",
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        ),
    ]
    db.session.add_all(campaigns)
    db.session.flush()

    donors = [
        Donor(name="Alice Johnson", email="alice@example.com", phone="555-0101",
              photo_url="https://i.pravatar.cc/150?img=47"),
        Donor(name="Bob Martinez", email="bob@example.com", phone="555-0102",
              photo_url="https://i.pravatar.cc/150?img=33"),
        Donor(name="Carol White", email="carol@example.com",
              photo_url="https://i.pravatar.cc/150?img=5"),
        Donor(name="David Lee", email="david@example.com", phone="555-0104",
              photo_url="https://i.pravatar.cc/150?img=11"),
        Donor(name="Eve Chen", email="eve@example.com",
              photo_url="https://i.pravatar.cc/150?img=9"),
    ]
    db.session.add_all(donors)
    db.session.flush()

    donations = [
        Donation(amount=5000,  date=date(2026, 1, 15), donor_id=donors[0].id, campaign_id=campaigns[0].id, note="Kickoff gift"),
        Donation(amount=2500,  date=date(2026, 2, 3),  donor_id=donors[1].id, campaign_id=campaigns[0].id),
        Donation(amount=10000, date=date(2026, 3, 10), donor_id=donors[0].id, campaign_id=campaigns[1].id, note="Founding donor"),
        Donation(amount=25000, date=date(2026, 4, 5),  donor_id=donors[3].id, campaign_id=campaigns[1].id, note="Major gift"),
        Donation(amount=1000,  date=date(2026, 2, 20), donor_id=donors[2].id, campaign_id=campaigns[2].id),
        Donation(amount=500,   date=date(2026, 3, 1),  donor_id=donors[4].id, campaign_id=campaigns[2].id),
        Donation(amount=5000,  date=date(2026, 3, 15), donor_id=donors[1].id, campaign_id=campaigns[2].id),
        Donation(amount=3000,  date=date(2026, 4, 20), donor_id=donors[2].id, campaign_id=campaigns[0].id),
        Donation(amount=1500,  date=date(2026, 5, 5),  donor_id=donors[4].id, campaign_id=campaigns[3].id),
        Donation(amount=8000,  date=date(2026, 5, 12), donor_id=donors[0].id, campaign_id=campaigns[3].id, note="Grateful supporter"),
    ]
    db.session.add_all(donations)
    db.session.commit()
    print("✓ Seeded sample data")


with app.app_context():
    db.create_all()
    seed_data()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
