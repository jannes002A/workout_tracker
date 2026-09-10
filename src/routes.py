from datetime import date as date_type

from flask import Blueprint, flash, redirect, render_template, request, url_for

from src import services
from src.models import FEELINGS
from src.services import (
    DEFAULT_WEIGHT,
    DURATION_CHOICES,
    MAX_AGE,
    MAX_COMMENT_LENGTH,
    MIN_AGE,
    REPETITION_CHOICES,
    WEIGHT_CHOICES,
    WEIGHT_UNIT,
    ValidationError,
)

bp = Blueprint("main", __name__)

REPS_FIELD_PREFIX = "reps-"  # one field per exercise: reps-<exercise id>
WEIGHT_FIELD_PREFIX = "weight-"  # and one for its extra weight: weight-<id>
EXTRA_NAME_FIELD = "extra-name"  # repeatable row of fields for the exercises
EXTRA_REPS_FIELD = "extra-reps"  # done in this session only
EXTRA_WEIGHT_FIELD = "extra-weight"
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
    """Page 1: create a workout with its exercises."""
    if request.method == "POST":
        try:
            workout = services.create_workout(
                request.form.get("name", ""),
                request.form.getlist("exercises"),
            )
            flash(f"Workout '{workout.name}' saved.", "success")
            return redirect(url_for("main.create"))
        except ValidationError as exc:
            flash(str(exc), "error")
    return render_template(
        "create.html",
        workouts=services.get_all_workouts(),
        known_exercises=services.known_exercise_names(),
    )


def _repetitions_from_form(form) -> dict[int, int]:
    """Read the per-exercise `reps-<exercise id>` fields off a submitted form."""
    return _by_exercise_id(form, REPS_FIELD_PREFIX)


def _weights_from_form(form) -> dict[int, int]:
    """Read the per-exercise `weight-<exercise id>` fields off a submitted form.

    An exercise with no field of its own is simply absent, which `log_session`
    reads as the default weight rather than as an error.
    """
    return _by_exercise_id(form, WEIGHT_FIELD_PREFIX)


def _by_exercise_id(form, prefix: str) -> dict[int, int]:
    """Collect the `<prefix><exercise id>` fields into an exercise id -> int map."""
    values = {}
    for key, value in form.items():
        if not key.startswith(prefix):
            continue
        exercise_id = int(key.removeprefix(prefix))
        values[exercise_id] = int(value)
    return values


def _extra_exercises_from_form(form) -> list[tuple[str, int, int]]:
    """Read the repeatable extra-exercise rows: a name, reps and weight each.

    The name and reps lists are zipped positionally. Weights are read by the
    same position but run out gracefully: a row with no weight field of its own
    is logged at DEFAULT_WEIGHT, the same fallback `log_session` applies to a
    exercise missing from `weights_by_exercise`. Rows left blank are dropped
    here so an untouched row never reaches the service (and so its unused
    number fields can't fail to parse).
    """
    names = form.getlist(EXTRA_NAME_FIELD)
    reps = form.getlist(EXTRA_REPS_FIELD)
    weights = form.getlist(EXTRA_WEIGHT_FIELD)
    return [
        (
            name,
            int(value),
            int(weights[i]) if i < len(weights) else DEFAULT_WEIGHT,
        )
        for i, (name, value) in enumerate(zip(names, reps))
        if name.strip()
    ]


@bp.route("/track", methods=["GET", "POST"])
def track():
    """Page 2: log a performed workout session, exercise by exercise."""
    if request.method == "POST":
        try:
            session = services.log_session(
                workout_id=int(request.form.get("workout_id", 0)),
                user_id=int(request.form.get(USER_FIELD, 0)),
                session_date=date_type.fromisoformat(request.form.get("date", "")),
                duration_minutes=int(request.form.get("duration", 0)),
                repetitions_by_exercise=_repetitions_from_form(request.form),
                weights_by_exercise=_weights_from_form(request.form),
                feeling=request.form.get("feeling", ""),
                extra_exercises=_extra_exercises_from_form(request.form),
                comment=request.form.get(COMMENT_FIELD, ""),
            )
            flash(
                f"Logged {session.workout.name} for {session.user.name} on "
                f"{session.date.isoformat()} "
                f"({session.total_repetitions} repetitions, "
                f"{session.total_weight} {WEIGHT_UNIT}).",
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
        weights=WEIGHT_CHOICES,
        weight_unit=WEIGHT_UNIT,
        feelings=FEELINGS,
        reps_prefix=REPS_FIELD_PREFIX,
        weight_prefix=WEIGHT_FIELD_PREFIX,
        extra_name_field=EXTRA_NAME_FIELD,
        extra_reps_field=EXTRA_REPS_FIELD,
        extra_weight_field=EXTRA_WEIGHT_FIELD,
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
        exercises=services.exercise_repetitions(user_id=user_id),
        trend=services.feeling_trend(user_id=user_id),
        comments=services.session_comments(user_id=user_id),
        trend_days=services.TREND_DAYS,
        comment_limit=services.COMMENT_LIMIT,
        users=services.get_all_users(),
        user=user,
        user_field=USER_FIELD,
        weight_unit=WEIGHT_UNIT,
    )


def _selected_user_id(args) -> int | None:
    """The user picked in the analytics dropdown, or None for 'All users'."""
    raw = args.get(USER_FIELD, "")
    return int(raw) if raw.isdigit() else None
