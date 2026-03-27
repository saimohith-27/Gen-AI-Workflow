from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session
import os
import re
import uuid
from datetime import datetime, timedelta
from dotenv import load_dotenv
from db import get_supabase_client, is_supabase_configured

from agents import (
    analyzer_agent,
    audit_agent,
    execution_agent,
    indent_analyzer_agent,
    monitoring_agent,
    priority_agent,
    routing_agent,
)
from db import get_supabase_client, is_supabase_configured

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev-secret")

IN_MEMORY_STORE = {}
IN_MEMORY_INDENTS = {}
VALID_DESIGNATIONS = {"hr", "manager", "lead", "sales", "legal", "pwd", "finance", "it"}
UNRESOLVED_STATUSES = {"pending", "in_progress", "escalated"}
UNRESOLVED_INDENT_STATUSES = {"pending_review", "under_review", "escalated"}


def init_database_connection():
    """Initialize Supabase client if credentials are configured."""
    if not is_supabase_configured():
        app.logger.warning(
            "Supabase credentials not found. Running without database connection."
        )
        return None

    try:
        client = get_supabase_client()
        app.logger.info("Supabase connection initialized.")
        return client
    except Exception as exc:
        app.logger.error(f"Failed to initialize Supabase connection: {exc}")
        return None


db_client = init_database_connection()


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return {
        "id": user_id,
        "email": session.get("user_email"),
        "display_name": session.get("display_name"),
        "role": session.get("role"),
        "designation": session.get("designation"),
        "created_at": session.get("created_at"),
    }


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please login first.")
            return redirect(url_for("login"))
        return func(*args, **kwargs)

    return wrapper


def owner_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please login first.")
            return redirect(url_for("login"))
        if session.get("role") != "owner":
            flash("Owner access required.")
            return redirect(url_for("dashboard"))
        return func(*args, **kwargs)

    return wrapper


def fetch_profile_by_user_id(user_id: str):
    if not db_client:
        return None
    response = (
        db_client.table("profiles")
        .select("id,email,display_name,role,designation,created_at,created_at")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        return None
    profile = response.data[0]
    if not profile.get("created_at"):
        profile["created_at"] = profile.get("created_at")
    return profile


def ensure_profile_for_oauth_user(user) -> dict | None:
    """Ensure profile row exists for OAuth-authenticated users."""
    if not user:
        return None

    existing = fetch_profile_by_user_id(user.id)
    if existing:
        return existing

    if not db_client:
        return None

    email = getattr(user, "email", None)
    metadata = getattr(user, "user_metadata", {}) or {}
    display_name = (
        metadata.get("full_name")
        or metadata.get("name")
        or (email.split("@")[0] if email else None)
        or "User"
    )

    try:
        db_client.table("profiles").insert(
            {
                "id": user.id,
                "email": email or f"{user.id}@oauth.local",
                "display_name": display_name,
                "role": "worker",
                "designation": None,
            }
        ).execute()
    except Exception as exc:
        app.logger.error(f"Failed to create OAuth profile for user {user.id}: {exc}")

    return fetch_profile_by_user_id(user.id)


def fetch_assignable_users():
    if not db_client:
        return []
    response = (
        db_client.table("profiles")
        .select("id,display_name,email,role,designation")
        .order("display_name")
        .execute()
    )
    return response.data or []


def infer_designation_for_complaint(analysis: dict, complaint: str) -> str:
    text = f"{complaint or ''} {analysis.get('category', '')} {analysis.get('summary', '')}".lower()

    rule_map = {
        "it": [
            "bug",
            "application",
            "app",
            "software",
            "system",
            "access",
            "password",
            "network",
            "server",
            "error",
            "crash",
            "login",
        ],
        "finance": ["invoice", "payment", "payroll", "budget", "reimbursement", "finance"],
        "hr": [
            "onboarding",
            "offboarding",
            "employee",
            "hiring",
            "leave",
            "hr",
            "salary",
            "hike",
            "increment",
            "compensation",
            "promotion",
        ],
        "legal": ["contract", "compliance", "legal", "policy", "nda"],
        "sales": ["sales", "client", "deal", "lead"],
        "pwd": ["road", "electricity", "water", "facility", "building", "infrastructure"],
        "lead": ["team lead", "cross-functional", "coordination"],
        "manager": ["approval", "escalation", "manager"],
    }

    for designation, keywords in rule_map.items():
        if any(keyword in text for keyword in keywords):
            return designation

    routed = str(analysis.get("routing", "")).strip().lower()
    if routed in VALID_DESIGNATIONS:
        return routed

    category = str(analysis.get("category", "")).strip().lower()
    routed_from_category = routing_agent(category)
    if routed_from_category in VALID_DESIGNATIONS:
        return routed_from_category

    return "manager"


def derive_sla_deadline_from_analysis(analysis: dict) -> str | None:
    """Convert AI-provided SLA text into an absolute UTC timestamp for storage."""
    if not isinstance(analysis, dict):
        return None

    raw_sla = analysis.get("sla")
    if raw_sla in (None, ""):
        return None

    # Accept numeric SLA as hours (e.g., 4 -> 4 hours).
    if isinstance(raw_sla, (int, float)):
        deadline = datetime.utcnow() + timedelta(hours=float(raw_sla))
        return deadline.replace(microsecond=0).isoformat() + "Z"

    text = str(raw_sla).strip()
    if not text:
        return None

    # If model already returns a timestamp, keep it after lightweight validation.
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed.replace(microsecond=0).isoformat() + "Z"
    except ValueError:
        pass

    match = re.search(
        r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>hours?|hrs?|hr|days?|day|minutes?|mins?|min)\b",
        text.lower(),
    )
    if not match:
        return None

    value = float(match.group("value"))
    unit = match.group("unit")
    if unit.startswith(("day", "d")):
        delta = timedelta(days=value)
    elif unit.startswith(("min", "m")):
        delta = timedelta(minutes=value)
    else:
        delta = timedelta(hours=value)

    deadline = datetime.utcnow() + delta
    return deadline.replace(microsecond=0).isoformat() + "Z"


def find_least_loaded_worker_by_designation(designation: str):
    if not db_client:
        return None

    profiles_response = (
        db_client.table("profiles")
        .select("id,display_name,email,role,designation")
        .eq("designation", designation)
        .execute()
    )
    designation_candidates = profiles_response.data or []
    worker_candidates = [c for c in designation_candidates if c.get("role") == "worker"]
    owner_candidates = [c for c in designation_candidates if c.get("role") == "owner"]
    candidates = worker_candidates or owner_candidates

    if not candidates and designation != "manager":
        profiles_response = (
            db_client.table("profiles")
            .select("id,display_name,email,role,designation")
            .eq("designation", "manager")
            .execute()
        )
        manager_candidates = profiles_response.data or []
        manager_workers = [c for c in manager_candidates if c.get("role") == "worker"]
        manager_owners = [c for c in manager_candidates if c.get("role") == "owner"]
        candidates = manager_workers or manager_owners

    if not candidates:
        return None

    counts = {candidate["id"]: 0 for candidate in candidates}
    unresolved_cases = (
        db_client.table("workflow_cases")
        .select("assigned_to,status")
        .in_("status", list(UNRESOLVED_STATUSES))
        .execute()
        .data
        or []
    )

    for case_item in unresolved_cases:
        assignee_id = case_item.get("assigned_to")
        if assignee_id in counts:
            counts[assignee_id] += 1

    ranked_candidates = sorted(
        candidates,
        key=lambda c: (
            counts.get(c["id"], 0),
            0 if c.get("role") == "worker" else 1,
            (c.get("display_name") or "").lower(),
        ),
    )
    return ranked_candidates[0]


def resolve_assignee_for_unresolved_case(record: dict):
    """Pick least-loaded worker for inferred designation when reassignment is needed."""
    analysis = record.get("analysis") or {}
    if not isinstance(analysis, dict):
        analysis = {}

    complaint = record.get("complaint") or ""
    target_designation = infer_designation_for_complaint(analysis, complaint)

    current_assignee_id = record.get("assigned_to")
    current_designation = None
    if current_assignee_id:
        current_profile = fetch_profile_by_user_id(current_assignee_id)
        if current_profile:
            current_designation = current_profile.get("designation")

    # Reassign if not assigned or assigned to a different function than inferred target.
    should_reassign = (not current_assignee_id) or (current_designation != target_designation)
    if not should_reassign:
        return None, target_designation

    best_candidate = find_least_loaded_worker_by_designation(target_designation)
    if not best_candidate:
        return None, target_designation

    if best_candidate.get("id") == current_assignee_id:
        return None, target_designation

    return best_candidate, target_designation


def find_least_loaded_indent_assignee(designation: str):
    if not db_client:
        return None

    profile_response = (
        db_client.table("profiles")
        .select("id,display_name,email,role,designation")
        .eq("designation", designation)
        .execute()
    )
    all_candidates = profile_response.data or []
    workers = [c for c in all_candidates if c.get("role") == "worker"]
    owners = [c for c in all_candidates if c.get("role") == "owner"]
    candidates = workers or owners

    if not candidates and designation != "manager":
        fallback_response = (
            db_client.table("profiles")
            .select("id,display_name,email,role,designation")
            .eq("designation", "manager")
            .execute()
        )
        fallback_candidates = fallback_response.data or []
        fallback_workers = [c for c in fallback_candidates if c.get("role") == "worker"]
        fallback_owners = [c for c in fallback_candidates if c.get("role") == "owner"]
        candidates = fallback_workers or fallback_owners

    if not candidates:
        return None

    counts = {candidate["id"]: 0 for candidate in candidates}
    unresolved_indents = (
        db_client.table("indent_requests")
        .select("assigned_to,status")
        .in_("status", list(UNRESOLVED_INDENT_STATUSES))
        .execute()
        .data
        or []
    )

    for indent_item in unresolved_indents:
        assignee_id = indent_item.get("assigned_to")
        if assignee_id in counts:
            counts[assignee_id] += 1

    ranked = sorted(
        candidates,
        key=lambda c: (
            counts.get(c["id"], 0),
            0 if c.get("role") == "worker" else 1,
            (c.get("display_name") or "").lower(),
        ),
    )
    return ranked[0]


def save_case_with_audit(case_payload: dict, audit_messages: list, actor_user_id: str):
    if not db_client:
        raise RuntimeError("Database not configured")

    case_response = db_client.table("workflow_cases").insert(case_payload).execute()
    if not case_response.data:
        raise RuntimeError("Failed to save workflow case")

    case_record = case_response.data[0]
    logs_payload = [
        {
            "case_id": case_record["id"],
            "actor_user_id": actor_user_id,
            "event_type": "info",
            "message": message,
        }
        for message in audit_messages
    ]
    if logs_payload:
        db_client.table("case_audit_logs").insert(logs_payload).execute()

    return case_record


def init_database_connection():
    """Initialize Supabase client if credentials are configured."""
    if not is_supabase_configured():
        app.logger.warning(
            "Supabase credentials not found. Running without database connection."
        )
        return None

    try:
        client = get_supabase_client()
        app.logger.info("Supabase connection initialized.")
        return client
    except Exception as exc:
        app.logger.error(f"Failed to initialize Supabase connection: {exc}")
        return None


db_client = init_database_connection()


# -------------------- ROUTES --------------------


@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return render_template("home.html")


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("home.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if not db_client:
            flash("Database is not configured. Add Supabase keys in .env first.")
            return redirect(url_for("login"))

        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Email and password are required.")
            return redirect(url_for("login"))

        try:
            auth_response = db_client.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
            user = auth_response.user
            if not user:
                flash("Invalid login credentials.")
                return redirect(url_for("login"))

            profile = fetch_profile_by_user_id(user.id)
            if not profile:
                flash("Profile not found. Ask owner to create your profile.")
                return redirect(url_for("login"))

            session["user_id"] = profile["id"]
            session["user_email"] = profile.get("email")
            session["display_name"] = profile.get("display_name")
            session["role"] = profile.get("role")
            session["designation"] = profile.get("designation")
            session["created_at"] = profile.get("created_at")

            flash("Login successful.")
            return redirect(url_for("dashboard"))
        except Exception as exc:
            flash(f"Login failed: {exc}")
            return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/auth/google")
def auth_google():
    if not db_client:
        flash("Database is not configured. Add Supabase keys in .env first.")
        return redirect(url_for("login"))

    try:
        redirect_to = os.getenv("OAUTH_REDIRECT_URL")
        oauth_response = db_client.auth.sign_in_with_oauth(
            {
                "provider": "google",
                "options": {"redirect_to": redirect_to},
            } 
        )

        provider_url = getattr(oauth_response, "url", None)
        if not provider_url and isinstance(oauth_response, dict):
            provider_url = oauth_response.get("url")

        if not provider_url:
            raise RuntimeError("Google OAuth URL was not returned by Supabase")

        return redirect(provider_url)
    except Exception as exc:
        flash(f"Unable to start Google sign in: {exc}")
        return redirect(url_for("login"))


@app.route("/auth/callback")
def auth_callback():
    if not db_client:
        flash("Database is not configured. Add Supabase keys in .env first.")
        return redirect(url_for("login"))

    auth_code = request.args.get("code")
    if not auth_code:
        flash("Google sign in failed: missing authorization code.")
        return redirect(url_for("login"))

    try:
        exchange = db_client.auth.exchange_code_for_session({"auth_code": auth_code})
        user = getattr(exchange, "user", None)
        if not user:
            user = getattr(getattr(exchange, "session", None), "user", None)

        profile = ensure_profile_for_oauth_user(user)
        if not profile:
            flash("Profile not found and could not be created for this Google account.")
            return redirect(url_for("login"))

        session["user_id"] = profile["id"]
        session["user_email"] = profile.get("email")
        session["display_name"] = profile.get("display_name")
        session["role"] = profile.get("role")
        session["designation"] = profile.get("designation")
        session["created_at"] = profile.get("created_at")

        flash("Google sign in successful.")
        return redirect(url_for("dashboard"))
    except Exception as exc:
        flash(f"Google sign in failed: {exc}")
        return redirect(url_for("login"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.")
    return redirect(url_for("index"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if not db_client:
        flash("Database is not configured.")
        return redirect(url_for("dashboard"))

    user_id = session.get("user_id")

    if request.method == "POST":
        display_name = request.form.get("display_name").strip()
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")
        created_at = request.form.get("created_at").strip()

        if not display_name:
            flash("Display name is required.")
            return redirect(url_for("profile"))

        if new_password:
            if len(new_password) < 6:
                flash("Password must be at least 6 characters.")
                return redirect(url_for("profile"))
            if new_password != confirm_password:
                flash("Password and confirm password must match.")
                return redirect(url_for("profile"))

        normalized_created_at = None
        if created_at:
            try:
                normalized_created_at = datetime.strptime(
                    created_at, "%Y-%m-%d"
                ).date().isoformat()
            except ValueError:
                flash("Date joined must be in YYYY-MM-DD format.")
                return redirect(url_for("profile"))

        update_payload = {
            "display_name": display_name,
        }

        try:
            db_client.table("profiles").update(update_payload).eq("id", user_id).execute()

            if new_password:
                db_client.auth.admin.update_user_by_id(
                    user_id,
                    {"password": new_password},
                )

            refreshed_profile = fetch_profile_by_user_id(user_id)
            if refreshed_profile:
                session["user_email"] = refreshed_profile.get("email")
                session["display_name"] = refreshed_profile.get("display_name")
                session["role"] = refreshed_profile.get("role")
                session["designation"] = refreshed_profile.get("designation")
                session["created_at"] = refreshed_profile.get("created_at")

            flash("Profile updated successfully.")
            return redirect(url_for("profile"))
        except Exception as exc:
            flash(f"Profile update failed: {exc}")
            return redirect(url_for("profile"))

    profile_data = fetch_profile_by_user_id(user_id)
    if not profile_data:
        flash("Profile not found.")
        return redirect(url_for("dashboard"))

    created_at_value = profile_data.get("created_at")
    if isinstance(created_at_value, str) and "T" in created_at_value:
        profile_data["created_at"] = created_at_value.split("T", 1)[0]

    return render_template("profile.html", profile=profile_data)


@app.route("/owner/users", methods=["GET", "POST"])
@owner_required
def owner_users():
    if not db_client:
        flash("Database is not configured.")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email").strip()
        display_name = request.form.get("display_name").strip()
        password = request.form.get("password")
        role = request.form.get("role").strip().lower()
        designation = request.form.get("designation").strip().lower()

        if role not in {"owner", "worker"}:
            flash("Role must be owner or worker.")
            return redirect(url_for("owner_users"))

        if designation not in VALID_DESIGNATIONS:
            flash("Designation must be one of: hr, manager, lead, sales, legal, pwd, finance, it.")
            return redirect(url_for("owner_users"))

        if not email or not display_name or not password:
            flash("Email, display name, and password are required.")
            return redirect(url_for("owner_users"))

        try:
            created = db_client.auth.admin.create_user(
                {
                    "email": email,
                    "password": password,
                    "email_confirm": True,
                }
            )
            new_user = created.user
            if not new_user:
                flash("User creation failed in auth.")
                return redirect(url_for("owner_users"))

            db_client.table("profiles").insert(
                {
                    "id": new_user.id,
                    "email": email,
                    "display_name": display_name,
                    "role": role,
                    "designation": designation,
                }
            ).execute()

            flash("New user created successfully.")
            return redirect(url_for("owner_users"))
        except Exception as exc:
            flash(f"User creation failed: {exc}")
            return redirect(url_for("owner_users"))

    users = (
        db_client.table("profiles")
        .select("id,email,display_name,role,designation,created_at")
        .order("created_at", desc=True)
        .execute()
        .data
    )
    return render_template("owner_users.html", users=users or [])


@app.route("/submit", methods=["GET", "POST"])
@login_required
def submit():
    logged_user = current_user()
    assignable_users = fetch_assignable_users()

    if request.method == "POST":
        name = request.form.get("name") or logged_user.get("display_name")
        email = request.form.get("email") or logged_user.get("email")
        location = request.form.get("location")
        complaint = request.form.get("complaint")
        manual_assigned_to = request.form.get("assigned_to") or None

        if not complaint:
            flash("Please enter a complaint.")
            return redirect(url_for("submit"))

        prompt = f"""
Location: {location}
Complaint: {complaint}
"""

        # 🧠 Step 1: Analyzer Agent
        analysis = analyzer_agent(prompt)

        # ⚠️ Step 2: Priority Agent
        priority = priority_agent(analysis)

        # ⏱️ AI-based SLA (converted to absolute UTC timestamp if parseable)
        sla_deadline = derive_sla_deadline_from_analysis(analysis)

        # 📍 Step 3: Routing Agent
        target_designation = infer_designation_for_complaint(analysis, complaint)
        officer = target_designation

        auto_assignee = None
        if not manual_assigned_to:
            auto_assignee = find_least_loaded_worker_by_designation(target_designation)
        assigned_to = manual_assigned_to or (auto_assignee.get("id") if auto_assignee else None)

        # 🔁 Step 4: Execution Agent
        status = execution_agent()

        # 📊 Step 5: Monitoring Agent
        status = monitoring_agent(status, priority)

        # 🧾 Step 6: Audit Trail
        audit_log = []
        audit_log = audit_agent(audit_log, "Complaint received")
        audit_log = audit_agent(audit_log, "Analyzed by AI")
        audit_log = audit_agent(audit_log, f"Priority set to {priority}")
        if sla_deadline:
            audit_log = audit_agent(audit_log, f"SLA set by AI to {sla_deadline}")
        else:
            audit_log = audit_agent(audit_log, "AI SLA unavailable; system fallback may apply")
        if auto_assignee:
            audit_log = audit_agent(
                audit_log,
                f"Assigned to {auto_assignee.get('display_name')} ({target_designation}) based on lowest unresolved load",
            )
        elif manual_assigned_to:
            audit_log = audit_agent(audit_log, "Assigned manually by requester")
        else:
            audit_log = audit_agent(
                audit_log,
                f"No eligible assignee found for {target_designation}; kept role-level assignment as {officer}",
            )
        audit_log = audit_agent(audit_log, f"Status updated to {status}")

        if db_client and logged_user:
            try:
                case_payload = {
                    "created_by": logged_user["id"],
                    "assigned_to": assigned_to,
                    "name": name,
                    "email": email,
                    "location": location,
                    "complaint": complaint,
                    "analysis": analysis,
                    "priority": priority,
                    "sla": sla_deadline,
                    "officer": officer,
                    "status": status.strip().lower(),
                }

                case_record = save_case_with_audit(
                    case_payload=case_payload,
                    audit_messages=audit_log,
                    actor_user_id=logged_user["id"],
                )
                return redirect(url_for("status", cid=case_record["id"]))
            except Exception as exc:
                flash(f"Database save failed, using local fallback: {exc}")

        cid = str(uuid.uuid4())
        IN_MEMORY_STORE[cid] = {
            "id": cid,
            "name": name,
            "email": email,
            "location": location,
            "complaint": complaint,
            "analysis": analysis,
            "priority": priority,
            "sla": sla_deadline,
            "officer": officer,
            "status": status,
            "audit_log": audit_log,
            "created_by": logged_user["id"] if logged_user else None,
            "assigned_to": assigned_to,
        }
        return redirect(url_for("status", cid=cid))

    return render_template(
        "submit.html",
        assignable_users=assignable_users,
        current_user=logged_user,
    )


@app.route("/cases")
@login_required
def cases():
    logged_user = current_user()
    logged_user_id = logged_user.get("id") if logged_user else None

    if not db_client:
        local_cases = list(IN_MEMORY_STORE.values())
        for case_item in local_cases:
            created_by_me = case_item.get("created_by") == logged_user_id
            assigned_to_me = case_item.get("assigned_to") == logged_user_id
            if created_by_me and assigned_to_me:
                case_item["case_scope"] = "created_and_assigned"
            elif created_by_me:
                case_item["case_scope"] = "created"
            elif assigned_to_me:
                case_item["case_scope"] = "assigned"
            else:
                case_item["case_scope"] = "visible"
        return render_template("cases.html", cases=local_cases)

    try:
        query = db_client.table("workflow_cases").select(
            "id,name,email,location,priority,status,officer,created_at,created_by,assigned_to"
        )
        if logged_user.get("role") == "owner":
            response = query.order("created_at", desc=True).execute()
        else:
            response = (
                query.or_(
                    f"created_by.eq.{logged_user['id']},assigned_to.eq.{logged_user['id']}"
                )
                .order("created_at", desc=True)
                .execute()
            )

        cases_data = response.data or []
        for case_item in cases_data:
            if logged_user.get("role") == "owner":
                case_item["case_scope"] = "all"
                continue

            created_by_me = case_item.get("created_by") == logged_user_id
            assigned_to_me = case_item.get("assigned_to") == logged_user_id
            if created_by_me and assigned_to_me:
                case_item["case_scope"] = "created_and_assigned"
            elif created_by_me:
                case_item["case_scope"] = "created"
            elif assigned_to_me:
                case_item["case_scope"] = "assigned"
            else:
                case_item["case_scope"] = "visible"

        return render_template("cases.html", cases=cases_data)
    except Exception as exc:
        flash(f"Unable to fetch cases: {exc}")
        return render_template("cases.html", cases=[])


@app.route("/status/<cid>", methods=["GET", "POST"])
@login_required
def status(cid):
    logged_user = current_user()
    logged_user_id = logged_user.get("id") if logged_user else None
    allowed_statuses = {"pending","escalated", "in_progress", "resolved", "closed"}
    record = None

    if db_client:
        try:
            response = (
                db_client.table("workflow_cases")
                .select(
                    "id,name,email,location,complaint,analysis,priority,sla,officer,status,created_by,assigned_to"
                )
                .eq("id", cid)
                .limit(1)
                .execute()
            )
            if response.data:
                record = response.data[0]
                logs_response = (
                    db_client.table("case_audit_logs")
                    .select("message,created_at")
                    .eq("case_id", cid)
                    .order("created_at")
                    .execute()
                )
                record["audit_log"] = [
                    item["message"] for item in (logs_response.data or [])
                ]
        except Exception as exc:
            flash(f"Could not load case from database: {exc}")

    if not record:
        record = IN_MEMORY_STORE.get(cid)

    if not record:
        return render_template("status.html", record=None, user_can_update=False)

    user_can_update = (
        logged_user.get("role") == "owner"
        or record.get("created_by") == logged_user_id
        or record.get("assigned_to") == logged_user_id
    )

    if request.method == "POST":
        if not user_can_update:
            flash("You are not allowed to update this case.")
            return redirect(url_for("status", cid=cid))

        new_status = request.form.get("status", "").strip().lower()
        remark = request.form.get("remark", "").strip()

        if new_status not in allowed_statuses:
            flash("Invalid status selected.")
            return redirect(url_for("status", cid=cid))

        if not remark:
            flash("Remark is required to update or close a case.")
            return redirect(url_for("status", cid=cid))

        actor_name = logged_user.get("display_name") or logged_user.get("email") or "User"
        audit_message = f"{actor_name} updated status to {new_status}. Remark: {remark}"

        if db_client:
            try:
                update_payload = {"status": new_status}
                reassignment_message = None

                if new_status in UNRESOLVED_STATUSES:
                    best_candidate, target_designation = resolve_assignee_for_unresolved_case(record)
                    if best_candidate:
                        update_payload["assigned_to"] = best_candidate.get("id")
                        update_payload["officer"] = target_designation
                        reassignment_message = (
                            f"Auto-reassigned to {best_candidate.get('display_name')} "
                            f"({target_designation}) based on lowest unresolved load"
                        )

                db_client.table("workflow_cases").update(update_payload).eq("id", cid).execute()
                db_client.table("case_audit_logs").insert(
                    {
                        "case_id": cid,
                        "actor_user_id": logged_user_id,
                        "event_type": "status_update",
                        "message": audit_message,
                    }
                ).execute()

                if reassignment_message:
                    db_client.table("case_audit_logs").insert(
                        {
                            "case_id": cid,
                            "actor_user_id": logged_user_id,
                            "event_type": "assignment_update",
                            "message": reassignment_message,
                        }
                    ).execute()
            except Exception as exc:
                flash(f"Could not update case: {exc}")
                return redirect(url_for("status", cid=cid))
        else:
            record["status"] = new_status
            if new_status in UNRESOLVED_STATUSES:
                best_candidate, target_designation = resolve_assignee_for_unresolved_case(record)
                if best_candidate:
                    record["assigned_to"] = best_candidate.get("id")
                    record["officer"] = target_designation
                    record.setdefault("audit_log", []).append(
                        f"Auto-reassigned to {best_candidate.get('display_name')} ({target_designation}) based on lowest unresolved load"
                    )
            record.setdefault("audit_log", []).append(audit_message)

        flash("Case updated successfully.")
        return redirect(url_for("status", cid=cid))

    return render_template("status.html", record=record, user_can_update=user_can_update)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/indent/raise", methods=["GET", "POST"])
@login_required
def raise_indent():
    logged_user = current_user()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        indent_text = request.form.get("indent_text", "").strip()
        budget_limit_raw = request.form.get("budget_limit", "").strip()

        if not title or not indent_text:
            flash("Indent title and details are required.")
            return redirect(url_for("raise_indent"))

        budget_limit = None
        if budget_limit_raw:
            try:
                budget_limit = float(budget_limit_raw)
            except ValueError:
                flash("Budget limit must be a valid number.")
                return redirect(url_for("raise_indent"))

        analysis = indent_analyzer_agent(indent_text)
        route_to_designation = str(analysis.get("route_to_designation", "manager")).lower()
        if route_to_designation not in VALID_DESIGNATIONS:
            route_to_designation = "manager"

        assignee = find_least_loaded_indent_assignee(route_to_designation) if db_client else None
        assigned_to = assignee.get("id") if assignee else None
        estimated_cost = float(analysis.get("estimated_cost", 0) or 0)
        cost_difference = (
            round(estimated_cost - budget_limit, 2) if budget_limit is not None else estimated_cost
        )

        if db_client:
            try:
                insert_payload = {
                    "created_by": logged_user["id"],
                    "assigned_to": assigned_to,
                    "title": title,
                    "indent_text": indent_text,
                    "category": analysis.get("category", "other"),
                    "route_to_designation": route_to_designation,
                    "estimated_cost": estimated_cost,
                    "budget_limit": budget_limit,
                    "cost_difference": cost_difference,
                    "status": "pending_review",
                    "ai_analysis": analysis,
                }
                insert_response = db_client.table("indent_requests").insert(insert_payload).execute()
                if not insert_response.data:
                    raise RuntimeError("Failed to create indent request")

                indent_record = insert_response.data[0]
                audit_messages = [
                    "Indent request raised",
                    f"AI analysis completed with category {analysis.get('category', 'other')}",
                    f"Estimated budget: {estimated_cost}",
                ]
                if assignee:
                    audit_messages.append(
                        f"Assigned to {assignee.get('display_name')} ({route_to_designation}) based on lowest pending load"
                    )
                else:
                    audit_messages.append(
                        f"No eligible assignee for {route_to_designation}; kept role-level assignment"
                    )

                db_client.table("indent_audit_logs").insert(
                    [
                        {
                            "indent_id": indent_record["id"],
                            "actor_user_id": logged_user["id"],
                            "event_type": "info",
                            "message": message,
                        }
                        for message in audit_messages
                    ]
                ).execute()

                flash("Indent request created successfully.")
                return redirect(url_for("indent_detail", indent_id=indent_record["id"]))
            except Exception as exc:
                flash(f"Indent creation failed: {exc}")
                return redirect(url_for("raise_indent"))

        indent_id = str(uuid.uuid4())
        IN_MEMORY_INDENTS[indent_id] = {
            "id": indent_id,
            "created_by": logged_user["id"],
            "assigned_to": assigned_to,
            "title": title,
            "indent_text": indent_text,
            "category": analysis.get("category", "other"),
            "route_to_designation": route_to_designation,
            "estimated_cost": estimated_cost,
            "budget_limit": budget_limit,
            "cost_difference": cost_difference,
            "status": "pending_review",
            "ai_analysis": analysis,
            "review_reason": None,
            "approved_cost": None,
            "audit_log": ["Indent request raised", "AI analysis completed"],
        }
        flash("Indent request created locally (database not configured).")
        return redirect(url_for("indent_detail", indent_id=indent_id))

    return render_template("raise_indent.html")


@app.route("/raise_indent")
@login_required
def indents():
    logged_user = current_user()
    logged_user_id = logged_user.get("id") if logged_user else None

    if db_client:
        try:
            query = db_client.table("indent_requests").select(
                "id,title,category,route_to_designation,estimated_cost,budget_limit,cost_difference,status,created_at,created_by,assigned_to"
            )
            if logged_user.get("role") == "owner":
                response = query.order("created_at", desc=True).execute()
            else:
                response = (
                    query.or_(
                        f"created_by.eq.{logged_user_id},assigned_to.eq.{logged_user_id}"
                    )
                    .order("created_at", desc=True)
                    .execute()
                )
            items = response.data or []
        except Exception as exc:
            flash(f"Could not fetch indent requests: {exc}")
            items = []
    else:
        items = list(IN_MEMORY_INDENTS.values())

    for item in items:
        created_by_me = item.get("created_by") == logged_user_id
        assigned_to_me = item.get("assigned_to") == logged_user_id
        if logged_user.get("role") == "owner":
            item["indent_scope"] = "all"
        elif created_by_me and assigned_to_me:
            item["indent_scope"] = "created_and_assigned"
        elif created_by_me:
            item["indent_scope"] = "created"
        elif assigned_to_me:
            item["indent_scope"] = "assigned"
        else:
            item["indent_scope"] = "visible"

    return render_template("indents.html", indents=items)


@app.route("/indent/<indent_id>", methods=["GET", "POST"])
@login_required
def indent_detail(indent_id):
    logged_user = current_user()
    logged_user_id = logged_user.get("id") if logged_user else None
    record = None

    if db_client:
        try:
            response = (
                db_client.table("indent_requests")
                .select(
                    "id,created_by,assigned_to,reviewed_by,title,indent_text,category,route_to_designation,estimated_cost,budget_limit,cost_difference,status,ai_analysis,review_reason,approved_cost,created_at,reviewed_at"
                )
                .eq("id", indent_id)
                .limit(1)
                .execute()
            )
            if response.data:
                record = response.data[0]
                logs = (
                    db_client.table("indent_audit_logs")
                    .select("message,created_at")
                    .eq("indent_id", indent_id)
                    .order("created_at")
                    .execute()
                    .data
                    or []
                )
                record["audit_log"] = [item["message"] for item in logs]
        except Exception as exc:
            flash(f"Could not fetch indent request: {exc}")

    if not record:
        record = IN_MEMORY_INDENTS.get(indent_id)

    if not record:
        return render_template("indent_detail.html", record=None, user_can_review=False)

    user_can_review = (
        logged_user.get("role") == "owner"
        or record.get("assigned_to") == logged_user_id
    )

    if request.method == "POST":
        if not user_can_review:
            flash("Only assigned reviewer or owner can approve/disapprove this indent.")
            return redirect(url_for("indent_detail", indent_id=indent_id))

        decision = request.form.get("decision", "").strip().lower()
        review_reason = request.form.get("review_reason", "").strip()
        approved_cost_raw = request.form.get("approved_cost", "").strip()

        if decision not in {"approved", "disapproved"}:
            flash("Decision must be approved or disapproved.")
            return redirect(url_for("indent_detail", indent_id=indent_id))

        if not review_reason:
            flash("Reason is required for approval/disapproval.")
            return redirect(url_for("indent_detail", indent_id=indent_id))

        approved_cost = None
        if approved_cost_raw:
            try:
                approved_cost = float(approved_cost_raw)
            except ValueError:
                flash("Approved cost must be a valid number.")
                return redirect(url_for("indent_detail", indent_id=indent_id))

        audit_message = f"{logged_user.get('display_name') or logged_user.get('email')} {decision} the indent. Reason: {review_reason}"

        if db_client:
            try:
                db_client.table("indent_requests").update(
                    {
                        "status": decision,
                        "review_reason": review_reason,
                        "approved_cost": approved_cost,
                        "reviewed_by": logged_user_id,
                        "reviewed_at": datetime.utcnow().isoformat(),
                    }
                ).eq("id", indent_id).execute()
                db_client.table("indent_audit_logs").insert(
                    {
                        "indent_id": indent_id,
                        "actor_user_id": logged_user_id,
                        "event_type": "review_decision",
                        "message": audit_message,
                    }
                ).execute()
            except Exception as exc:
                flash(f"Could not save review decision: {exc}")
                return redirect(url_for("indent_detail", indent_id=indent_id))
        else:
            record["status"] = decision
            record["review_reason"] = review_reason
            record["approved_cost"] = approved_cost
            record["reviewed_by"] = logged_user_id
            record.setdefault("audit_log", []).append(audit_message)

        flash("Indent reviewed successfully.")
        return redirect(url_for("indent_detail", indent_id=indent_id))

    return render_template("indent_detail.html", record=record, user_can_review=user_can_review)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", use_reloader=False)
