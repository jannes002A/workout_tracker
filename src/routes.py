from datetime import date as date_type

from flask import Blueprint, flash, redirect, render_template, request, url_for

from src import services
from src.models import FEELINGS
from src.services import (
    DURATION_CHOICES,
    MAX_AGE,
    MAX_COMMENT_LENGTH,
    MIN_AGE,
    REPETITION_CHOICES,
    ValidationError,
)

bp = Blueprint("main", __name__)

REPS_FIELD_PREFIX = "reps-"  # one field per movement: reps-<movement id>
EXTRA_NAME_FIELD = "extra-name"  # repeatable pair of fields for the movements
EXTRA_REPS_FIELD = "extra-reps"  # done in this session only
USER_FIELD = "user_id"  # picks the user on /track, filters /analytics
COMMENT_FIELD = "comment"  # the session's free-text note


@bp.route("/")
def index():
    return redirect(url_for("main.create"))


@bp.route("/users", methods=["GET", "POST"])
def users():
    """Page 0: create the people whose sessions are tracked."""
    if request.method == "POST":
        try:
            user = services.create_user(
                request.form.get("name", ""),
                _age_from_form(request.form),
            )
            flash(f"User '{user.name}' saved.", "success")
            return redirect(url_for("main.users"))
        except ValidationError as exc:
            flash(str(exc), "error")
    return render_template(
        "users.html",
        users=services.get_all_users(),
        min_age=MIN_AGE,
        max_age=MAX_AGE,
    )


def _age_from_form(form) -> int:
    """Read the age field. Anything unparseable becomes an out-of-range 0,
    so the service produces the same message as a number that is out of range."""
    try:
        return int(form.get("age", ""))
    except ValueError:
        return 0


@bp.route("/create", methods=["GET", "POST"])
def create():
    """Page 1: create a workout with its movements."""
    if request.method == "POST":
        try:
            workout = services.create_workout(
                request.form.get("name", ""),
                request.form.getlist("movements"),
            )
            flash(f"Workout '{workout.name}' saved.", "success")
            return redirect(url_for("main.create"))
        except ValidationError as exc:
            flash(str(exc), "error")
    return render_template(
        "create.html",
        workouts=services.get_all_workouts(),
        known_movements=services.known_movement_names(),
    )


def _repetitions_from_form(form) -> dict[int, int]:
    """Read the per-movement `reps-<movement id>` fields off a submitted form."""
    reps = {}
    for key, value in form.items():
        if not key.startswith(REPS_FIELD_PREFIX):
            continue
        movement_id = int(key.removeprefix(REPS_FIELD_PREFIX))
        reps[movement_id] = int(value)
    return reps


def _extra_movements_from_form(form) -> list[tuple[str, int]]:
    """Read the repeatable extra-movement rows: a name and a reps field each.

    Rows left blank are dropped here so an untouched row never reaches the
    service (and so its unused reps field can't fail to parse).
    """
    names = form.getlist(EXTRA_NAME_FIELD)
    reps = form.getlist(EXTRA_REPS_FIELD)
    return [
        (name, int(value))
        for name, value in zip(names, reps)
        if name.strip()
    ]


@bp.route("/track", methods=["GET", "POST"])
def track():
    """Page 2: log a performed workout session, movement by movement."""
    if request.method == "POST":
        try:
            session = services.log_session(
                workout_id=int(request.form.get("workout_id", 0)),
                user_id=int(request.form.get(USER_FIELD, 0)),
                session_date=date_type.fromisoformat(request.form.get("date", "")),
                duration_minutes=int(request.form.get("duration", 0)),
                repetitions_by_movement=_repetitions_from_form(request.form),
                feeling=request.form.get("feeling", ""),
                extra_movements=_extra_movements_from_form(request.form),
                comment=request.form.get(COMMENT_FIELD, ""),
            )
            flash(
                f"Logged {session.workout.name} for {session.user.name} on "
                f"{session.date.isoformat()} "
                f"({session.total_repetitions} repetitions).",
                "success",
            )
            return redirect(url_for("main.track"))
        except (ValidationError, ValueError) as exc:
            flash(str(exc), "error")
    return render_template(
        "track.html",
        workouts=services.get_all_workouts(),
        users=services.get_all_users(),
        user_field=USER_FIELD,
        dates=services.date_choices(),
        durations=DURATION_CHOICES,
        repetitions=REPETITION_CHOICES,
        feelings=FEELINGS,
        reps_prefix=REPS_FIELD_PREFIX,
        extra_name_field=EXTRA_NAME_FIELD,
        extra_reps_field=EXTRA_REPS_FIELD,
        comment_field=COMMENT_FIELD,
        max_comment_length=MAX_COMMENT_LENGTH,
    )


@bp.route("/analytics")
def analytics():
    """Page 3: activity map, workouts performed, repetitions, feeling trend.

    A `user_id` in the query string narrows every section to that user; without
    it — or with an id that no longer exists — the page covers everyone.
    """
    user = services.get_user(_selected_user_id(request.args))
    user_id = user.id if user else None
    return render_template(
        "analytics.html",
        activity=services.activity_map(user_id=user_id),
        frequency=services.workout_frequency(user_id=user_id),
        movements=services.movement_repetitions(user_id=user_id),
        trend=services.feeling_trend(user_id=user_id),
        comments=services.session_comments(user_id=user_id),
        trend_days=services.TREND_DAYS,
        users=services.get_all_users(),
        user=user,
        user_field=USER_FIELD,
    )


def _selected_user_id(args) -> int | None:
    """The user picked in the analytics dropdown, or None for 'All users'."""
    raw = args.get(USER_FIELD, "")
    return int(raw) if raw.isdigit() else None
