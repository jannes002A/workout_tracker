from datetime import date as date_type

from flask import Blueprint, flash, redirect, render_template, request, url_for

from src import services
from src.models import DEFAULT_CATEGORY, FEELINGS
from src.services import (
    DEFAULT_SETS,
    DEFAULT_TRACKING_MODE,
    DEFAULT_WEIGHT,
    DURATION_CHOICES,
    NO_WEIGHT,
    MAX_AGE,
    MAX_CATEGORY_LABEL,
    MAX_COMMENT_LENGTH,
    MIN_AGE,
    REPETITION_CHOICES,
    SET_CHOICES,
    SETS_MODE,
    TRACKING_MODES,
    WEIGHT_CHOICES,
    WEIGHT_UNIT,
    ValidationError,
)

bp = Blueprint("main", __name__)

REPS_FIELD_PREFIX = "reps-"  # one field per exercise: reps-<exercise id>
WEIGHT_FIELD_PREFIX = "weight-"  # and one for its extra weight: weight-<id>
SETS_FIELD_PREFIX = "sets-"  # and one for its sets: sets-<id>, in sets mode
EXTRA_NAME_FIELD = "extra-name"  # repeatable row of fields for the exercises
EXTRA_REPS_FIELD = "extra-reps"  # done in this session only
EXTRA_WEIGHT_FIELD = "extra-weight"
EXTRA_SETS_FIELD = "extra-sets"
MODE_FIELD = "tracking_mode"  # counts the session in totals or in sets
CATEGORY_FIELD = "category"  # the workout's sort of sport, on the create form
CATEGORY_LABEL_FIELD = "label"  # names the sort of sport being added
NO_WEIGHT_VALUE = ""  # the weight dropdown's "no extra weight" option
USER_FIELD = "user_id"  # picks the user on /track, filters /analytics
DAY_FIELD = "day"  # the day of the activity map /analytics is opened on
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
                # Missing entirely — a hand-crafted POST — is the default sort
                # of sport; a value the dropdown cannot have produced is an
                # error, the way an unknown feeling is on the track page.
                request.form.get(CATEGORY_FIELD, DEFAULT_CATEGORY),
            )
            flash(
                f"Workout '{workout.name}' saved "
                f"({workout.category_label.lower()}).",
                "success",
            )
            return redirect(url_for("main.create"))
        except ValidationError as exc:
            flash(str(exc), "error")
    return render_template(
        "create.html",
        workouts=services.get_all_workouts(),
        known_exercises=services.known_exercise_names(),
        categories=services.category_map(),
        default_category=DEFAULT_CATEGORY,
        category_field=CATEGORY_FIELD,
        category_label_field=CATEGORY_LABEL_FIELD,
        max_category_label=MAX_CATEGORY_LABEL,
    )


@bp.route("/categories", methods=["POST"])
def add_category():
    """Add a sort of sport, from the small form under the create page's panel.

    A page of its own would be a page with one field on it, and the dropdown
    it fills is on /create, so this posts from there and goes straight back —
    the new sort of sport then being one of the dropdown's options.
    """
    try:
        category = services.create_category(
            request.form.get(CATEGORY_LABEL_FIELD, "")
        )
        flash(f"Sort of sport '{category.label}' added.", "success")
    except ValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("main.create"))


def _repetitions_from_form(form) -> dict[int, int]:
    """Read the per-exercise `reps-<exercise id>` fields off a submitted form."""
    return _by_exercise_id(form, REPS_FIELD_PREFIX)


def _weights_from_form(form) -> dict[int, int | None]:
    """Read the per-exercise `weight-<exercise id>` fields off a submitted form.

    An exercise with no field of its own is simply absent, which `log_session`
    reads as the default weight rather than as an error. A field left at the
    dropdown's "no extra weight" option maps to NO_WEIGHT, the same thing.
    """
    return _by_exercise_id(form, WEIGHT_FIELD_PREFIX, _weight)


def _weight(raw: str) -> int | None:
    """Parse one weight field: NO_WEIGHT for the blank "no extra weight" option."""
    return NO_WEIGHT if raw.strip() == NO_WEIGHT_VALUE else int(raw)


def _by_exercise_id(form, prefix: str, parse=int) -> dict[int, int]:
    """Collect the `<prefix><exercise id>` fields into an exercise id -> value map."""
    values = {}
    for key, value in form.items():
        if not key.startswith(prefix):
            continue
        exercise_id = int(key.removeprefix(prefix))
        values[exercise_id] = parse(value)
    return values


def _tracking_mode(form) -> str:
    """Which way the form counted the session, from the dropdown at its top.

    Anything the dropdown cannot have produced — only reachable by a
    hand-crafted POST — falls back to DEFAULT_TRACKING_MODE, the way an unknown
    user id on the analytics page falls back to "All users".
    """
    mode = form.get(MODE_FIELD, "").strip()
    return mode if mode in TRACKING_MODES else DEFAULT_TRACKING_MODE


def _sets_from_form(form) -> dict[int, int | None]:
    """Read the per-exercise `sets-<exercise id>` fields off a submitted form.

    Only in sets mode. Counting a session in totals, the repetitions dropdown
    already carries the whole figure for the exercise, so the sets fields — which
    a browser without JS submits all the same — are ignored, exactly as the
    fields of the workouts that weren't picked are.
    """
    if _tracking_mode(form) != SETS_MODE:
        return {}
    return _by_exercise_id(form, SETS_FIELD_PREFIX)


def _extra_exercises_from_form(form) -> list[tuple[str, int, int | None, int | None]]:
    """Read the repeatable extra-exercise rows: a name, reps, weight and sets.

    The name and reps lists are zipped positionally. Weights and sets are read
    by the same position but run out gracefully: a row with no field of its own
    is logged at DEFAULT_WEIGHT and DEFAULT_SETS, the same fallbacks
    `log_session` applies to an exercise missing from `weights_by_exercise` or
    `sets_by_exercise`. The sets are read only in sets mode, like the ones of
    the workout's own exercises. Rows left blank are dropped here so an
    untouched row never reaches the service (and so its unused number fields
    can't fail to parse).
    """
    names = form.getlist(EXTRA_NAME_FIELD)
    reps = form.getlist(EXTRA_REPS_FIELD)
    weights = form.getlist(EXTRA_WEIGHT_FIELD)
    sets = (
        form.getlist(EXTRA_SETS_FIELD)
        if _tracking_mode(form) == SETS_MODE
        else []
    )
    return [
        (
            name,
            int(value),
            _weight(weights[i]) if i < len(weights) else DEFAULT_WEIGHT,
            int(sets[i]) if i < len(sets) else DEFAULT_SETS,
        )
        for i, (name, value) in enumerate(zip(names, reps))
        if name.strip()
    ]


@bp.route("/track", methods=["GET", "POST"])
@bp.route("/track/<int:session_id>", methods=["GET", "POST"])
def track(session_id: int | None = None):
    """Page 2: log a performed workout session, exercise by exercise.

    With a `session_id` — the "correct this session" link on the analytics
    page's day panel — the same page and the same form open on a session that
    already exists, every field filled in with what was logged, and saving
    writes that session again instead of adding another. A session id nothing
    answers to takes the user back to the analytics page with a message, the
    way an unknown day there renders without its panel.
    """
    editing = services.get_session(session_id)
    if session_id is not None and editing is None:
        flash("That session no longer exists.", "error")
        return redirect(url_for("main.analytics"))
    if request.method == "POST":
        try:
            fields = dict(
                workout_id=int(request.form.get("workout_id", 0)),
                user_id=int(request.form.get(USER_FIELD, 0)),
                session_date=date_type.fromisoformat(request.form.get("date", "")),
                duration_minutes=int(request.form.get("duration", 0)),
                repetitions_by_exercise=_repetitions_from_form(request.form),
                weights_by_exercise=_weights_from_form(request.form),
                sets_by_exercise=_sets_from_form(request.form),
                feeling=request.form.get("feeling", ""),
                extra_exercises=_extra_exercises_from_form(request.form),
                comment=request.form.get(COMMENT_FIELD, ""),
            )
            if editing:
                session = services.update_session(editing.id, **fields)
                flash(f"Updated {_session_summary(session)}", "success")
                # Back to the day it now falls on, which is where the link in
                # was: the correction is there to be seen.
                return redirect(
                    url_for(
                        "main.analytics",
                        **{DAY_FIELD: session.date.isoformat()},
                        _anchor="day",
                    )
                )
            session = services.log_session(**fields)
            flash(f"Logged {_session_summary(session)}", "success")
            return redirect(url_for("main.track"))
        except (ValidationError, ValueError) as exc:
            flash(str(exc), "error")
    return render_template(
        "track.html",
        workouts=services.get_all_workouts(),
        users=services.get_all_users(),
        user_field=USER_FIELD,
        # The form's own fields, read back off the session being corrected —
        # None when tracking a new one, which is what the template branches on.
        editing=services.session_form(editing) if editing else None,
        # A session older than the dropdown reaches still has to be offered
        # its own date, or saving would silently move it.
        dates=services.date_choices(include=editing.date if editing else None),
        durations=DURATION_CHOICES,
        repetitions=REPETITION_CHOICES,
        weights=WEIGHT_CHOICES,
        set_choices=SET_CHOICES,
        no_weight_value=NO_WEIGHT_VALUE,
        tracking_modes=TRACKING_MODES,
        default_tracking_mode=DEFAULT_TRACKING_MODE,
        sets_mode=SETS_MODE,
        mode_field=MODE_FIELD,
        weight_unit=WEIGHT_UNIT,
        feelings=FEELINGS,
        reps_prefix=REPS_FIELD_PREFIX,
        weight_prefix=WEIGHT_FIELD_PREFIX,
        sets_prefix=SETS_FIELD_PREFIX,
        extra_name_field=EXTRA_NAME_FIELD,
        extra_reps_field=EXTRA_REPS_FIELD,
        extra_weight_field=EXTRA_WEIGHT_FIELD,
        extra_sets_field=EXTRA_SETS_FIELD,
        comment_field=COMMENT_FIELD,
        max_comment_length=MAX_COMMENT_LENGTH,
    )


def _session_summary(session) -> str:
    """What a session flashes as once it is saved, logged or corrected."""
    # A session of nothing but bodyweight exercises has no weight to report,
    # so it is summed up in repetitions alone.
    moved = f", {session.total_weight} {WEIGHT_UNIT}" if session.total_weight else ""
    return (
        f"{session.workout.name} for {session.user.name} on "
        f"{session.date.isoformat()} "
        f"({session.category_label.lower()}, "
        f"{session.total_repetitions} repetitions{moved})."
    )


@bp.route("/analytics")
def analytics():
    """Page 3: activity map, workouts performed, repetitions, feeling trend.

    A `user_id` in the query string narrows every section to that user; without
    it — or with an id that no longer exists — the page covers everyone. A `day`
    opens the activity map on that date, listing the sessions behind its cell;
    that is a link on every day that has one, so the drill-down needs no JS.
    """
    user = services.get_user(_selected_user_id(request.args))
    user_id = user.id if user else None
    day = _selected_day(request.args)
    return render_template(
        "analytics.html",
        activity=services.activity_map(user_id=user_id),
        day=day,
        day_field=DAY_FIELD,
        # Nothing to list until a day is picked, and the query is skipped
        # entirely rather than asked about a date that isn't there.
        day_sessions=services.day_sessions(day, user_id=user_id) if day else [],
        frequency=services.workout_frequency(user_id=user_id),
        exercises=services.exercise_repetitions(user_id=user_id),
        trend=services.feeling_trend(user_id=user_id),
        comments=services.session_comments(user_id=user_id),
        trend_days=services.TREND_DAYS,
        comment_limit=services.COMMENT_LIMIT,
        users=services.get_all_users(),
        user=user,
        user_field=USER_FIELD,
        categories=services.category_map(),
        weight_unit=WEIGHT_UNIT,
    )


def _selected_user_id(args) -> int | None:
    """The user picked in the analytics dropdown, or None for 'All users'."""
    raw = args.get(USER_FIELD, "")
    return int(raw) if raw.isdigit() else None


def _selected_day(args) -> date_type | None:
    """The day the activity map was clicked on, or None when none was.

    Anything that isn't a date — only reachable by editing the query string —
    falls back to None, the way an unknown user id falls back to "All users",
    so a hand-crafted link renders the page without its day panel rather than
    raising.
    """
    try:
        return date_type.fromisoformat(args.get(DAY_FIELD, ""))
    except ValueError:
        return None
