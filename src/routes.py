from datetime import date as date_type

from flask import Blueprint, flash, redirect, render_template, request, url_for

from src import services
from src.models import FEELINGS
from src.services import DURATION_CHOICES, REPETITION_CHOICES, ValidationError

bp = Blueprint("main", __name__)

REPS_FIELD_PREFIX = "reps-"  # one field per movement: reps-<movement id>
EXTRA_NAME_FIELD = "extra-name"  # repeatable pair of fields for the movements
EXTRA_REPS_FIELD = "extra-reps"  # done in this session only


@bp.route("/")
def index():
    return redirect(url_for("main.create"))


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
                session_date=date_type.fromisoformat(request.form.get("date", "")),
                duration_minutes=int(request.form.get("duration", 0)),
                repetitions_by_movement=_repetitions_from_form(request.form),
                feeling=request.form.get("feeling", ""),
                extra_movements=_extra_movements_from_form(request.form),
            )
            flash(
                f"Logged {session.workout.name} on {session.date.isoformat()} "
                f"({session.total_repetitions} repetitions).",
                "success",
            )
            return redirect(url_for("main.track"))
        except (ValidationError, ValueError) as exc:
            flash(str(exc), "error")
    return render_template(
        "track.html",
        workouts=services.get_all_workouts(),
        dates=services.date_choices(),
        durations=DURATION_CHOICES,
        repetitions=REPETITION_CHOICES,
        feelings=FEELINGS,
        reps_prefix=REPS_FIELD_PREFIX,
        extra_name_field=EXTRA_NAME_FIELD,
        extra_reps_field=EXTRA_REPS_FIELD,
    )


@bp.route("/analytics")
def analytics():
    """Page 3: activity map, workouts performed, repetitions, feeling trend."""
    return render_template(
        "analytics.html",
        activity=services.activity_map(),
        frequency=services.workout_frequency(),
        movements=services.movement_repetitions(),
        trend=services.feeling_trend(),
        trend_days=services.TREND_DAYS,
    )
