"""Core application logic.

Every function here is covered by a test in the tests/ folder.
Keeping logic out of the route handlers makes it easy to test without HTTP.
"""

import math
import re
from datetime import date as date_type
from datetime import timedelta

from src.models import (
    CATEGORY_PALETTE,
    DEFAULT_CATEGORIES,
    DEFAULT_CATEGORY,
    FEELING_SCORES,
    FEELINGS,
    Category,
    Exercise,
    SessionExercise,
    User,
    Workout,
    WorkoutSession,
    category_by_value,
    db,
)

DURATION_CHOICES = list(range(10, 91, 5))  # 10-90 minutes
REPETITION_CHOICES = list(range(0, 121))  # 0-120, 0 meaning skipped
WEIGHT_CHOICES = list(range(1, 201))  # 1-200, the extra weight per exercise
NO_WEIGHT = None  # the "no extra weight" choice: repetitions only, no load
DEFAULT_WEIGHT = NO_WEIGHT  # what an unanswered weight field means
SET_CHOICES = list(range(1, 21))  # 1-20 sets of an exercise within a session
NO_SETS = None  # the repetitions given are already the exercise's total
DEFAULT_SETS = NO_SETS  # what an unanswered sets field means
# How the track page counts a session, picked from a dropdown at the top of the
# form: value -> the label the dropdown shows for it. Counting in sets asks for
# the repetitions of one set per exercise and multiplies them by its sets; the
# two come out at the same place, the repetitions logged for that exercise.
TOTAL_MODE, SETS_MODE = "total", "sets"
TRACKING_MODES = {
    TOTAL_MODE: "Total repetitions per exercise",
    SETS_MODE: "Sets × repetitions per set",
}
DEFAULT_TRACKING_MODE = TOTAL_MODE
WEIGHT_UNIT = "kg"  # only ever displayed; nothing converts between units
TREND_DAYS = 30  # window of the feeling graph on the analytics page
EXERCISE_HEATMAP_DAYS = 365  # window of each per-exercise heatmap
COMMENT_LIMIT = 5  # how many session notes the analytics page lists
MIN_AGE, MAX_AGE = 1, 120  # bounds of the age field, and of its error message
MAX_CATEGORY_LABEL = 40  # cap on the name of a sort of sport, and its input's
MAX_COMMENT_LENGTH = 2000  # cap on a session's free-text note


class ValidationError(ValueError):
    """Raised when user input is invalid."""


# ------------------------------------------------------------------- users


def create_user(name: str, age: int) -> User:
    """Create a user. Names are unique, compared case-insensitively."""
    name = (name or "").strip()
    if not name:
        raise ValidationError("User name is required.")
    if not isinstance(age, int) or not MIN_AGE <= age <= MAX_AGE:
        raise ValidationError(f"Age must be between {MIN_AGE} and {MAX_AGE}.")
    if User.query.filter(db.func.lower(User.name) == name.lower()).first():
        raise ValidationError(f"A user named '{name}' already exists.")

    user = User(name=name, age=age)
    db.session.add(user)
    db.session.commit()
    return user


def get_all_users() -> list[User]:
    """All users, alphabetically."""
    return User.query.order_by(User.name).all()


def get_user(user_id: int | None) -> User | None:
    """The user with that id, or None for a missing id or an unknown one."""
    if user_id is None:
        return None
    return db.session.get(User, user_id)


# ------------------------------------------------------------- categories


def ensure_categories() -> None:
    """Put the four sorts of sport of DEFAULT_CATEGORIES in an empty table.

    Called once per app from `create_app`, right after `db.create_all()`, so a
    fresh database comes with Weights, Judo, Mobility and Others rather than an
    empty dropdown. A sort of sport already there is left exactly as it is, and
    the ones added on the create page are never touched, so this is safe to run
    at every startup.
    """
    empty = not db.session.query(Category.id).first()
    added = False
    for index, (value, label, color) in enumerate(DEFAULT_CATEGORIES):
        if category_by_value(value):
            continue
        db.session.add(
            Category(
                value=value,
                label=label,
                color=color,
                # An empty table takes the order of DEFAULT_CATEGORIES; a
                # default put back into a table that has grown its own sorts
                # of sport goes after them instead of taking their place.
                position=index if empty else _next_position(),
            )
        )
        added = True
    if added:
        db.session.commit()


def _next_position() -> int:
    """The position a sort of sport added now takes: last in the list."""
    highest = db.session.query(db.func.max(Category.position)).scalar()
    return 0 if highest is None else highest + 1


def get_all_categories() -> list[Category]:
    """Every sort of sport, in the order the dropdowns and the legend list them."""
    return Category.query.order_by(Category.position, Category.id).all()


def category_map() -> dict[str, Category]:
    """Every sort of sport as value -> row, in that same order.

    This is what the templates are handed: they look a stored value up in it to
    draw a label and a colour, and iterate it for the dropdowns and the map's
    legend, so neither can name a sort of sport the table doesn't hold.
    """
    return {category.value: category for category in get_all_categories()}


def category_labels() -> list[str]:
    """The labels, in order — what an error message names the choices with."""
    return [category.label for category in get_all_categories()]


def create_category(label: str) -> Category:
    """Add a sort of sport, e.g. 'Running', from the create page.

    The stored `value` is derived from the label, so the label is what the user
    types and the value is what workouts and sessions carry. Labels are unique
    compared case-insensitively, and so are the values they reduce to, which is
    what stops 'Trail running' and 'trail-running' becoming two sorts of sport
    that colour the same.

    The colour is assigned rather than asked for: the first of CATEGORY_PALETTE
    that no category is using yet, so a new sort of sport is told apart from the
    ones already on the activity map without a colour picker on the form.
    """
    label = (label or "").strip()
    if not label:
        raise ValidationError("Name the sort of sport you want to add.")
    if len(label) > MAX_CATEGORY_LABEL:
        raise ValidationError(
            f"Keep the sort of sport under {MAX_CATEGORY_LABEL} characters."
        )
    value = _category_value(label)
    if not value:
        raise ValidationError("Use at least one letter or number in the name.")
    clash = Category.query.filter(
        db.or_(db.func.lower(Category.label) == label.lower(), Category.value == value)
    ).first()
    if clash:
        raise ValidationError(f"'{clash.label}' is already a sort of sport.")

    category = Category(
        value=value,
        label=label,
        color=_next_category_color(),
        position=_next_position(),
    )
    db.session.add(category)
    db.session.commit()
    return category


def _category_value(label: str) -> str:
    """The stored value a label reduces to: lowercase, punctuation as hyphens."""
    return re.sub(r"\W+", "-", label.casefold(), flags=re.UNICODE).strip("-")


def _next_category_color() -> str:
    """The colour a sort of sport added now gets.

    The first palette entry nothing is using, so the seeded four keep their own
    colours and every addition looks different — until the palette is used up,
    at which point it starts over rather than leaving a category colourless.
    """
    taken = {color for (color,) in db.session.query(Category.color).distinct()}
    free = [color for color in CATEGORY_PALETTE if color not in taken]
    if free:
        return free[0]
    return CATEGORY_PALETTE[Category.query.count() % len(CATEGORY_PALETTE)]


# ---------------------------------------------------------------- workouts


def create_workout(
    name: str, exercise_names: list[str], category: str = DEFAULT_CATEGORY
) -> Workout:
    """Create a workout with its exercises. Empty exercise names are dropped.

    `category` is the sort of sport the workout is — the value of one of the
    `Category` rows, picked from the dropdown at the top of the create form.
    Every session of the workout is logged under it. It defaults to
    DEFAULT_CATEGORY, so a caller — or a hand-crafted POST — that leaves it out
    still creates a workout; a value the dropdown cannot have produced is
    rejected the way an unknown feeling is on the track page.
    """
    name = (name or "").strip()
    exercises, seen = [], set()
    for raw in exercise_names:
        exercise = (raw or "").strip()
        if not exercise or exercise.casefold() in seen:
            continue  # blank field, or the same exercise picked twice
        seen.add(exercise.casefold())
        exercises.append(exercise)
    if not name:
        raise ValidationError("Workout name is required.")
    if not exercises:
        raise ValidationError("Add at least one exercise.")
    if Workout.query.filter_by(name=name).first():
        raise ValidationError(f"A workout named '{name}' already exists.")
    if not category_by_value(category):
        # Built from the labels the dropdown is filled with, so the message and
        # the options it names cannot drift apart.
        raise ValidationError(
            f"Sort of sport must be one of {', '.join(category_labels())}."
        )

    workout = Workout(name=name, category=category)
    workout.exercises = [Exercise(name=m) for m in exercises]
    db.session.add(workout)
    db.session.commit()
    return workout


def get_all_workouts() -> list[Workout]:
    """All workouts, alphabetically."""
    return Workout.query.order_by(Workout.name).all()


def known_exercise_names() -> list[str]:
    """Every exercise name already in the log, sorted case-insensitively.

    Covers the exercises of existing workouts as well as extras logged on the
    track page, so the create page can offer any of them for reuse.
    """
    names = {name for (name,) in db.session.query(Exercise.name).distinct()}
    extras = (
        db.session.query(SessionExercise.extra_name)
        .filter(SessionExercise.exercise_id.is_(None))
        .distinct()
    )
    names |= {name for (name,) in extras if name}
    return sorted(names, key=str.casefold)


# ---------------------------------------------------------------- sessions


def _check_weight(weight: int | None, exercise_name: str) -> None:
    """Reject an extra weight outside WEIGHT_CHOICES, naming the exercise.

    NO_WEIGHT passes: it is the track page's default, meaning the exercise was
    done with no added load and counts in repetitions only. The message is
    built from the ends of the list, the same one the track page's dropdown is
    filled from, so the two cannot drift apart.
    """
    if weight is NO_WEIGHT:
        return
    if weight not in WEIGHT_CHOICES:
        raise ValidationError(
            f"Weight for '{exercise_name}' must be between "
            f"{WEIGHT_CHOICES[0]} and {WEIGHT_CHOICES[-1]}."
        )


def _check_sets(sets: int | None, exercise_name: str) -> None:
    """Reject a number of sets outside SET_CHOICES, naming the exercise.

    NO_SETS passes: it means the session was counted as a total per exercise
    rather than in sets, which is the track page's default. The message is
    built from the ends of the list the dropdown is filled from, so the two
    cannot drift apart.
    """
    if sets is NO_SETS:
        return
    if sets not in SET_CHOICES:
        raise ValidationError(
            f"Sets for '{exercise_name}' must be between "
            f"{SET_CHOICES[0]} and {SET_CHOICES[-1]}."
        )


def _performed(repetitions: int, sets: int | None) -> int:
    """The repetitions actually performed, which is what gets logged.

    Counted as a total, that is the figure given. Counted in sets, the figure
    is the repetitions of one set and the sets multiply it.
    """
    return repetitions if sets is NO_SETS else repetitions * sets


def log_session(
    workout_id: int,
    user_id: int,
    session_date: date_type,
    duration_minutes: int,
    repetitions_by_exercise: dict[int, int],
    feeling: str,
    extra_exercises: (
        list[tuple[str, int]]
        | list[tuple[str, int, int | None]]
        | list[tuple[str, int, int | None, int | None]]
        | None
    ) = None,
    comment: str = "",
    weights_by_exercise: dict[int, int | None] | None = None,
    sets_by_exercise: dict[int, int | None] | None = None,
) -> WorkoutSession:
    """Record a performed workout by one user, exercise by exercise.

    `update_session` takes exactly these arguments and applies them to a
    session that already exists, so what the track form can log it can also
    correct; `_fill_session` is the half the two share.

    `repetitions_by_exercise` maps exercise id -> repetitions. Every exercise of
    the workout must be present; ids belonging to other workouts are ignored,
    because the track form submits fields for all workouts when JS is off.

    `weights_by_exercise` maps the same exercise ids to the extra weight carried
    for those repetitions, or to NO_WEIGHT for an exercise done with no added
    load. Unlike the repetitions it is optional per exercise: an id missing from
    it is logged at DEFAULT_WEIGHT — NO_WEIGHT — so a caller that does not care
    about weight, or a form submitted without the field, records a session of
    plain repetitions rather than failing.

    `sets_by_exercise` maps those same exercise ids to the number of sets the
    exercise was done in, which is what the track page's "sets" mode collects.
    An exercise with a number of sets has its `repetitions_by_exercise` figure
    read as the repetitions of *one* set, and the two are multiplied into the
    repetitions logged; NO_SETS — the default for an id missing from the map,
    and for every exercise when the session is counted as a total — logs the
    figure as it stands.

    `extra_exercises` holds (name, repetitions), (name, repetitions, weight) or
    (name, repetitions, weight, sets) tuples for exercises done in this session
    only, the weight and sets again defaulting to DEFAULT_WEIGHT and
    DEFAULT_SETS. They are logged against the session without being added to the
    workout, so they never show up on the track form again. Tuples with a blank
    name are dropped, so an untouched row on the form is simply ignored.

    `comment` is a free-text note about the session. It is stripped, and a blank
    one is stored as NULL rather than an empty string, so `session_comments` can
    pick out the sessions that actually have something to say.

    The session's sort of sport is not asked for: it is copied from the
    workout, which is where it is picked (on the create page). Storing it on
    the session is what keeps the activity map honest about the past — a
    workout given a different sort of sport later does not recolour the days it
    was already performed on.
    """
    session = WorkoutSession()
    _fill_session(
        session,
        workout_id=workout_id,
        user_id=user_id,
        session_date=session_date,
        duration_minutes=duration_minutes,
        repetitions_by_exercise=repetitions_by_exercise,
        feeling=feeling,
        extra_exercises=extra_exercises,
        comment=comment,
        weights_by_exercise=weights_by_exercise,
        sets_by_exercise=sets_by_exercise,
    )
    db.session.add(session)
    db.session.commit()
    return session


def update_session(
    session_id: int,
    workout_id: int,
    user_id: int,
    session_date: date_type,
    duration_minutes: int,
    repetitions_by_exercise: dict[int, int],
    feeling: str,
    extra_exercises: (
        list[tuple[str, int]]
        | list[tuple[str, int, int | None]]
        | list[tuple[str, int, int | None, int | None]]
        | None
    ) = None,
    comment: str = "",
    weights_by_exercise: dict[int, int | None] | None = None,
    sets_by_exercise: dict[int, int | None] | None = None,
) -> WorkoutSession:
    """Write a session that was logged wrongly again, from the same fields.

    This is the track form opened on a session that already exists: every
    argument means what it means in `log_session`, and the session ends up as
    if it had been logged that way in the first place. Nothing is patched in
    place — the exercise logs are replaced wholesale (the old ones are deleted
    by the cascade), which is what lets the workout itself be corrected: the
    logs then belong to the exercises of the workout now chosen, and the sort
    of sport is copied from it again.

    The session keeps its id, so the day it now falls on is the only place it
    shows up. An id nothing answers to is a ValidationError rather than a
    crash, the way an unknown workout is.
    """
    session = get_session(session_id)
    if session is None:
        raise ValidationError("That session no longer exists.")
    _fill_session(
        session,
        workout_id=workout_id,
        user_id=user_id,
        session_date=session_date,
        duration_minutes=duration_minutes,
        repetitions_by_exercise=repetitions_by_exercise,
        feeling=feeling,
        extra_exercises=extra_exercises,
        comment=comment,
        weights_by_exercise=weights_by_exercise,
        sets_by_exercise=sets_by_exercise,
    )
    db.session.commit()
    return session


def get_session(session_id: int | None) -> WorkoutSession | None:
    """The session with that id, or None for a missing id or an unknown one."""
    if session_id is None:
        return None
    return db.session.get(WorkoutSession, session_id)


def _fill_session(
    session: WorkoutSession,
    workout_id: int,
    user_id: int,
    session_date: date_type,
    duration_minutes: int,
    repetitions_by_exercise: dict[int, int],
    feeling: str,
    extra_exercises,
    comment: str,
    weights_by_exercise: dict[int, int | None] | None,
    sets_by_exercise: dict[int, int | None] | None,
) -> None:
    """Validate a session's fields and put them on `session`, logs and all.

    Everything is checked and every log built before a single attribute is
    assigned, so a session being corrected is left exactly as it was when the
    new values don't hold up — the route re-renders the form and nothing has
    half-changed underneath it.
    """
    workout = db.session.get(Workout, workout_id)
    if not workout:
        raise ValidationError("Select a workout that exists.")
    if not db.session.get(User, user_id):
        raise ValidationError("Select a user that exists.")
    if duration_minutes not in DURATION_CHOICES:
        raise ValidationError("Duration must be between 10 and 90 minutes.")
    if feeling not in FEELINGS:
        raise ValidationError("Feeling must be good, okay or bad.")
    if not isinstance(session_date, date_type):
        raise ValidationError("Invalid date.")
    comment = (comment or "").strip()
    if len(comment) > MAX_COMMENT_LENGTH:
        raise ValidationError(
            f"Keep the comment under {MAX_COMMENT_LENGTH} characters."
        )

    provided = repetitions_by_exercise or {}
    weights = weights_by_exercise or {}
    sets_of = sets_by_exercise or {}
    logs = []
    for exercise in workout.exercises:
        if exercise.id not in provided:
            raise ValidationError(f"Enter repetitions for '{exercise.name}'.")
        reps = provided[exercise.id]
        if reps not in REPETITION_CHOICES:
            raise ValidationError(
                f"Repetitions for '{exercise.name}' must be between "
                f"{REPETITION_CHOICES[0]} and {REPETITION_CHOICES[-1]}."
            )
        sets = sets_of.get(exercise.id, DEFAULT_SETS)
        _check_sets(sets, exercise.name)
        weight = weights.get(exercise.id, DEFAULT_WEIGHT)
        _check_weight(weight, exercise.name)
        logs.append(
            SessionExercise(
                exercise_id=exercise.id,
                repetitions=_performed(reps, sets),
                sets=sets,
                weight=weight,
            )
        )

    of_workout = {exercise.name.casefold() for exercise in workout.exercises}
    seen_extras: set[str] = set()
    for entry in extra_exercises or []:
        name, reps = entry[0], entry[1]
        weight = entry[2] if len(entry) > 2 else DEFAULT_WEIGHT
        sets = entry[3] if len(entry) > 3 else DEFAULT_SETS
        name = (name or "").strip()
        if not name:
            continue  # an untouched extra-exercise row on the form
        if name.casefold() in of_workout:
            raise ValidationError(
                f"'{name}' is already an exercise of {workout.name} — "
                "set its repetitions above."
            )
        if name.casefold() in seen_extras:
            raise ValidationError(f"Add the extra exercise '{name}' only once.")
        if reps not in REPETITION_CHOICES:
            raise ValidationError(
                f"Repetitions for '{name}' must be between "
                f"{REPETITION_CHOICES[0]} and {REPETITION_CHOICES[-1]}."
            )
        _check_sets(sets, name)
        _check_weight(weight, name)
        seen_extras.add(name.casefold())
        logs.append(
            SessionExercise(
                extra_name=name,
                repetitions=_performed(reps, sets),
                sets=sets,
                weight=weight,
            )
        )

    session.workout_id = workout_id
    session.user_id = user_id
    session.date = session_date
    session.duration_minutes = duration_minutes
    session.feeling = feeling
    session.category = workout.category  # the sort of sport, as it stands today
    session.comment = comment or None
    # Assigning the collection deletes whatever was logged before: the cascade
    # is delete-orphan, so a corrected session leaves no stray logs behind.
    session.logs = logs


def session_form(session: WorkoutSession) -> dict:
    """A session as the track form's own fields, for editing it.

    The shape mirrors what the form submits rather than what the database
    holds: {"id", "workout_id", "user_id", "date", "duration_minutes",
    "feeling", "comment", "tracking_mode", "repetitions", "weights", "sets",
    "extras"}, the three maps keyed by exercise id and `extras` a list of
    {"name", "repetitions", "weight", "sets"}.

    A session with any exercise counted in sets comes back in SETS_MODE, where
    the repetitions of a dropdown are the repetitions of *one* set — so that is
    what `repetitions` carries there, and re-saving an untouched form logs
    exactly what is already stored. An exercise logged as a total inside such a
    session is read back as one set of its total, which comes to the same
    thing.
    """
    in_sets = any(log.tracked_in_sets for log in session.logs)
    logs = [log for log in session.logs if not log.is_extra]
    return {
        "id": session.id,
        "workout_id": session.workout_id,
        "user_id": session.user_id,
        "date": session.date,
        "duration_minutes": session.duration_minutes,
        "feeling": session.feeling,
        "comment": session.comment or "",
        "tracking_mode": SETS_MODE if in_sets else TOTAL_MODE,
        "repetitions": {
            log.exercise_id: _form_repetitions(log, in_sets) for log in logs
        },
        "weights": {log.exercise_id: log.weight for log in logs},
        "sets": {log.exercise_id: _form_sets(log, in_sets) for log in logs},
        "extras": [
            {
                "name": log.extra_name,
                "repetitions": _form_repetitions(log, in_sets),
                "weight": log.weight,
                "sets": _form_sets(log, in_sets),
            }
            for log in session.logs
            if log.is_extra
        ],
    }


def _form_repetitions(log: SessionExercise, in_sets: bool) -> int:
    """What the repetitions dropdown shows for a log: per set, or the total."""
    if in_sets and log.tracked_in_sets:
        return log.repetitions_per_set
    return log.repetitions


def _form_sets(log: SessionExercise, in_sets: bool) -> int | None:
    """What the sets dropdown shows: NO_SETS unless the form counts in sets."""
    if not in_sets:
        return NO_SETS
    return log.sets or 1  # a total, inside a session counted in sets


def date_choices(
    days_back: int = 30,
    today: date_type | None = None,
    include: date_type | None = None,
) -> list[date_type]:
    """Dates for the date dropdown: today plus the previous `days_back` days.

    `include` adds one date the window would otherwise leave out — the date of
    a session being edited, which can be older than the dropdown reaches. The
    list stays newest first, so the extra date lands where it belongs rather
    than at the end.
    """
    today = today or date_type.today()
    days = [today - timedelta(days=i) for i in range(days_back + 1)]
    if include and include not in days:
        days = sorted([*days, include], reverse=True)
    return days


# ---------------------------------------------------------------- analytics


def _filtered(query, user_id: int | None, category: str | None):
    """Narrow a query that selects sessions down to one user and one sport.

    Every analytics function takes a `user_id` and a `category`; None means
    "everyone" and "every sort of sport", which is what the page shows until
    something is picked from its dropdowns. The sport is the session's own
    copy, `WorkoutSession.category` — the one the activity map colours a day
    by — so re-labelling a workout does not move its past sessions from one
    filter to another. Apply this before grouping, so the filter lands in the
    WHERE clause.
    """
    if user_id is not None:
        query = query.filter(WorkoutSession.user_id == user_id)
    if category is not None:
        query = query.filter(WorkoutSession.category == category)
    return query


# The SQL twin of SessionExercise.weight_moved: the extra weight counted once
# per repetition of it, which is what the analytics page totals as "weight".
# NULL for a log with no extra weight, exactly as the property is None, so
# SUM() skips those rows and a bodyweight set adds nothing to a weight total.
_WEIGHT_MOVED = SessionExercise.repetitions * SessionExercise.weight

# How many of the logs grouped here carried an extra weight. COUNT() of a
# column ignores NULLs, so this is 0 for an exercise only ever done at
# bodyweight — the rows whose weight figures the analytics page leaves out
# rather than printing as 0.
_WEIGHTED_LOGS = db.func.count(SessionExercise.weight)


def _calendar_weeks(
    counts: dict[date_type, int],
    end: date_type,
    days: int,
    categories: dict[date_type, str] | None = None,
) -> dict:
    """Bucket per-day counts into a GitHub-style grid of Monday-first weeks.

    Returns {"weeks": [[cell, ...] x7 per week], "max": int, "months": [...]}
    where each cell is {"date": iso string, "count": int, "level": 0-4,
    "category": str | None} or None for the padding days before the window
    starts. Levels are relative to the busiest day, and counts outside the
    window are ignored.

    `categories` maps a day to the sort of sport it should be coloured by,
    which is what the activity map uses to tell one category from another. A
    day it says nothing about — every day of a per-exercise grid, where a cell
    counts repetitions rather than sessions — gets `category` None and is
    shaded with the default scale.

    `months` labels the x axis: one {"label": "Sep 2025", "weeks": int} per run
    of week columns, so the labels can be laid out above the grid. A week is
    attributed to the month of its first day, so a label sits above the first
    week that starts in that month. Their `weeks` sum to the number of columns.
    """
    start = end - timedelta(days=days - 1)
    counts = {day: count for day, count in counts.items() if start <= day <= end}
    categories = categories or {}
    max_count = max(counts.values(), default=0)

    def level(count: int) -> int:
        if count == 0 or max_count == 0:
            return 0
        return math.ceil(4 * count / max_count)

    weeks: list[list] = []
    week: list = [None] * start.weekday()  # pad so weeks start on Monday
    current = start
    while current <= end:
        count = counts.get(current, 0)
        week.append(
            {
                "date": current.isoformat(),
                "count": count,
                "level": level(count),
                "category": categories.get(current),
            }
        )
        if len(week) == 7:
            weeks.append(week)
            week = []
        current += timedelta(days=1)
    if week:
        weeks.append(week + [None] * (7 - len(week)))

    months: list[dict] = []
    for week in weeks:
        first = next(cell for cell in week if cell)
        label = date_type.fromisoformat(first["date"]).strftime("%b %Y")
        if months and months[-1]["label"] == label:
            months[-1]["weeks"] += 1
        else:
            months.append({"label": label, "weeks": 1})

    return {"weeks": weeks, "max": max_count, "months": months}


def _repetition_trend(sessions: list[tuple[date_type, int, int]]) -> dict:
    """Whether an exercise's repetitions went up, down or held last time.

    Compares the last two sessions the exercise was logged in, given as
    (date, session id, repetitions) triples in any order. They are ordered by
    date and then by session id, so two sessions on one day compete in the
    order they were logged rather than being merged. Returns
    {"direction": "up" | "down" | "similar" | None, "previous": int,
     "latest": int, "change": int | None, "previous_date": date | None,
     "latest_date": date | None}, where `change` is the absolute difference
    in repetitions, latest minus previous. Only no difference at all counts
    as "similar".

    `direction` and `change` are None for an exercise logged in fewer than two
    sessions, which is too little to read a trend from.
    """
    if len(sessions) < 2:
        return {
            "direction": None,
            "previous": 0,
            "latest": 0,
            "change": None,
            "previous_date": None,
            "latest_date": None,
        }

    (previous_date, _, previous), (latest_date, _, latest) = sorted(sessions)[-2:]
    change = latest - previous
    direction = "up" if change > 0 else "down" if change < 0 else "similar"
    return {
        "direction": direction,
        "previous": previous,
        "latest": latest,
        "change": change,
        "previous_date": previous_date,
        "latest_date": latest_date,
    }


def _category_rank(category: str, order: dict[str, int]) -> int:
    """Where a category sits in the stored order, which is what breaks a tie.

    A value the category table no longer holds — only reachable through a
    session logged before that sort of sport was deleted — sorts last rather
    than raising.
    """
    return order.get(category, len(order))


def activity_map(
    end: date_type | None = None,
    days: int = 365,
    user_id: int | None = None,
    category: str | None = None,
) -> dict:
    """GitHub-style activity data: one cell per day for the last `days` days.

    Cells count the sessions logged that day, by `user_id` or by everyone; see
    `_calendar_weeks` for the returned shape.

    Each day also carries the `category` its cell is coloured by: the sort of
    sport most of that day's sessions were. A day holding two sorts in equal
    numbers takes whichever comes first in the category table, so the colour of
    a day never depends on the order the rows came back in. A day with no
    session has no category at all.
    """
    end = end or date_type.today()
    start = end - timedelta(days=days - 1)

    rows = (
        _filtered(
            db.session.query(
                WorkoutSession.date,
                WorkoutSession.category,
                db.func.count(WorkoutSession.id),
            ).filter(WorkoutSession.date >= start, WorkoutSession.date <= end),
            user_id,
            category,
        )
        .group_by(WorkoutSession.date, WorkoutSession.category)
        .all()
    )

    order = {value: index for index, value in enumerate(category_map())}
    counts: dict[date_type, int] = {}
    categories: dict[date_type, str] = {}
    ranking: dict[date_type, tuple[int, int]] = {}
    for day, category, count in rows:
        counts[day] = counts.get(day, 0) + count
        # Most sessions wins; the order of the category table settles a tie.
        rank = (-count, _category_rank(category, order))
        if day not in ranking or rank < ranking[day]:
            ranking[day] = rank
            categories[day] = category

    return _calendar_weeks(counts, end, days, categories)


def day_sessions(
    day: date_type, user_id: int | None = None, category: str | None = None
) -> list[dict]:
    """Everything logged on one day, in the order it was logged.

    This is what a click on a cell of the activity map opens: the sessions
    behind that one cell, for the user the page is filtered to. Each entry is
    {"id", "category", "category_label", "workout", "user", "duration_minutes",
    "feeling", "comment", "repetitions", "weight", "exercises": [...]}, and
    each exercise in turn is {"name", "repetitions", "sets",
    "repetitions_per_set", "weight", "weight_moved", "extra"} — the same shape
    the track form filled in, read back.

    The figures come off the models rather than being re-summed in SQL, so a
    day reports exactly what `WorkoutSession.total_repetitions`, `total_weight`
    and `SessionExercise.weight_moved` say everywhere else. An exercise's
    `weight` is None — not 0 — when it was done at bodyweight, exactly as the
    column is, so the page can leave the weight out instead of printing 0. The
    exercises keep the order they were logged in, which puts the workout's own
    ahead of the extras. `comment` is None when the session carries no note.

    Sessions come back oldest-logged first, the id standing in for the time of
    day the way it does in `session_comments`. The list is empty when nothing
    was logged that day — or nothing by that user, which is why a day that is
    a link on one person's map need not be one on another's.
    """
    sessions = (
        _filtered(
            WorkoutSession.query.filter(WorkoutSession.date == day),
            user_id,
            category,
        )
        .order_by(WorkoutSession.id)
        .all()
    )
    return [
        {
            # what the panel's "correct this session" link points at
            "id": session.id,
            "category": session.category,
            "category_label": session.category_label,
            "workout": session.workout.name,
            "user": session.user.name,
            "duration_minutes": session.duration_minutes,
            "feeling": session.feeling,
            "comment": session.comment,
            "repetitions": session.total_repetitions,
            "weight": session.total_weight,
            "exercises": [
                {
                    "name": log.name,
                    "repetitions": log.repetitions,
                    "sets": log.sets,
                    "repetitions_per_set": log.repetitions_per_set,
                    "weight": log.weight,
                    "weight_moved": log.weight_moved,
                    "extra": log.is_extra,
                }
                for log in session.logs
            ],
        }
        for session in sessions
    ]


def workout_frequency(
    user_id: int | None = None, category: str | None = None
) -> list[dict]:
    """How often each workout has been done and how it felt, most frequent first.

    Each row is {"name": str, "count": int, "feelings": {feeling: count}}, with
    a `feelings` entry for every value in FEELINGS.

    Across everyone and every sport the table doubles as a list of what exists,
    so workouts never performed are included with a count of 0. For a single
    user or a single sort of sport those rows are just noise, so a `user_id` or
    a `category` lists only the workouts actually performed under that filter —
    an inner join rather than an outer one.
    """
    on_workout = WorkoutSession.workout_id == Workout.id
    query = db.session.query(Workout.name, db.func.count(WorkoutSession.id))
    if user_id is None and category is None:
        query = query.outerjoin(WorkoutSession, on_workout)
    else:
        query = _filtered(query.join(WorkoutSession, on_workout), user_id, category)
    rows = query.group_by(Workout.id).all()
    by_feeling = (
        _filtered(
            db.session.query(
                Workout.name,
                WorkoutSession.feeling,
                db.func.count(WorkoutSession.id),
            ).join(WorkoutSession, WorkoutSession.workout_id == Workout.id),
            user_id,
            category,
        )
        .group_by(Workout.name, WorkoutSession.feeling)
        .all()
    )
    feelings = {name: dict.fromkeys(FEELINGS, 0) for name, _ in rows}
    for name, feeling, count in by_feeling:
        feelings[name][feeling] = count

    return sorted(
        [
            {"name": name, "count": count, "feelings": feelings[name]}
            for name, count in rows
        ],
        key=lambda r: (-r["count"], r["name"]),
    )


def exercise_repetitions(
    end: date_type | None = None,
    user_id: int | None = None,
    category: str | None = None,
) -> list[dict]:
    """Repetitions per exercise across every workout, most repetitions first.

    Exercises are grouped by name, so an exercise that appears in several
    workouts — or that was done once as an extra — is reported as a single row
    with its combined total.

    `workouts` names where the repetitions came from: the workouts of the
    sessions the exercise was logged in, *not* every workout that has an exercise
    of that name. An extra belongs to no workout, so one done only as an extra
    lists none, even when a workout the user never touched happens to contain a
    exercise with the same name. For an exercise nobody has performed there are
    no sessions to go on, so it falls back to the workouts it belongs to — the
    only thing there is to say about it. `extra` says whether the exercise was
    ever logged as a session-only extra. Exercises never performed are included
    with a total of 0.

    `weight` is the weight moved across the exercise's whole history: the extra
    weight of each log counted once per repetition of it, the same figure as
    `SessionExercise.weight_moved`. Sets done with no extra weight are left out
    of it — they are counted in `repetitions` alone — and `weighted` says
    whether any set carried a weight at all. An exercise only ever done at
    bodyweight has `weighted` False, `weight` 0 and `best_session` None, which
    is what lets the page report it in repetitions only instead of captioning it
    with a weight of 0.

    `best_session` is the single session that accounts for most of the weight —
    {"weight": int, "date": a `date`, formatted in the template} — or None for
    an exercise never performed or never weighted, much as `heatmap` is None for
    one never performed. Sessions with no extra weight are not candidates, so
    the best session is always a session that actually carried something. Two
    sessions tied on weight are reported at the later date. Unlike `heatmap`
    both read the whole history rather than the last EXERCISE_HEATMAP_DAYS days,
    so a best session can predate the grid it is shown above.

    `trend` says whether its repetitions went up, down or held between the last
    two sessions it was logged in; see `_repetition_trend`. Those sessions can
    predate the window drawn in `heatmap`.

    `heatmap` is the exercise's history as a calendar grid of the last
    EXERCISE_HEATMAP_DAYS days — the same shape as `activity_map`, but with each
    cell counting repetitions instead of sessions, shaded relative to that
    exercise's own busiest day. Repetitions are summed when an exercise was done
    more than once on a date, which can happen across two sessions.

    Filtering by `user_id` narrows the sessions counted *and* the exercises
    listed: an exercise that user has never performed is dropped rather than
    reported at 0, since the whole list would otherwise be padded with rows
    from workouts they have never touched. Without a `user_id` those rows stay,
    so the page doubles as a list of every exercise that exists. An exercise
    logged with 0 repetitions still counts as performed — it was part of the
    session — which is the same line the "Not performed yet" label draws.
    """
    end = end or date_type.today()
    buckets: dict[str, dict] = {}

    def bucket(name: str) -> dict:
        return buckets.setdefault(
            name,
            {
                "name": name,
                "repetitions": 0,
                "weight": 0,
                "weighted": False,
                "times": 0,
                "workouts": [],
                "extra": False,
                "heatmap": None,
                "best_session": None,
                "trend": _repetition_trend([]),
            },
        )

    # Exercises that belong to a workout, whether or not they were ever done.
    # Membership alone does not earn a workout a place in `workouts` — see the
    # `performed_in` query below — but it is what gives an exercise nobody has
    # done a row at all.
    member_of: dict[str, set[str]] = {}
    pairs = (
        db.session.query(Exercise.name, Workout.name)
        .join(Workout, Exercise.workout_id == Workout.id)
        .all()
    )
    for exercise_name, workout_name in pairs:
        bucket(exercise_name)
        member_of.setdefault(exercise_name, set()).add(workout_name)

    # The workouts an exercise's repetitions actually came from, taken from the
    # session each one was logged in. An extra contributes nothing here, which
    # is what keeps an exercise done only as an extra from being labelled with
    # the workout that happens to have an exercise of the same name.
    performed_in: dict[str, set[str]] = {}
    for exercise_name, workout_name in _filtered(
        db.session.query(Exercise.name, Workout.name)
        .join(SessionExercise, SessionExercise.exercise_id == Exercise.id)
        .join(WorkoutSession, WorkoutSession.id == SessionExercise.session_id)
        .join(Workout, Workout.id == WorkoutSession.workout_id),
        user_id,
        category,
    ).distinct():
        performed_in.setdefault(exercise_name, set()).add(workout_name)

    logged = (
        _filtered(
            db.session.query(
                Exercise.name,
                db.func.sum(SessionExercise.repetitions),
                db.func.sum(_WEIGHT_MOVED),
                db.func.count(SessionExercise.id),
                _WEIGHTED_LOGS,
            )
            .join(SessionExercise, SessionExercise.exercise_id == Exercise.id)
            .join(WorkoutSession, WorkoutSession.id == SessionExercise.session_id),
            user_id,
            category,
        )
        .group_by(Exercise.name)
        .all()
    )
    for name, reps, weight, times, weighted in logged:
        row = bucket(name)
        row["repetitions"] += int(reps or 0)
        row["weight"] += int(weight or 0)
        row["times"] += times
        row["weighted"] = row["weighted"] or bool(weighted)

    # Extras carry their own name instead of pointing at an exercise row.
    extras = (
        _filtered(
            db.session.query(
                SessionExercise.extra_name,
                db.func.sum(SessionExercise.repetitions),
                db.func.sum(_WEIGHT_MOVED),
                db.func.count(SessionExercise.id),
                _WEIGHTED_LOGS,
            )
            .join(WorkoutSession, WorkoutSession.id == SessionExercise.session_id)
            .filter(SessionExercise.exercise_id.is_(None)),
            user_id,
            category,
        )
        .group_by(SessionExercise.extra_name)
        .all()
    )
    for name, reps, weight, times, weighted in extras:
        row = bucket(name)
        row["repetitions"] += int(reps or 0)
        row["weight"] += int(weight or 0)
        row["times"] += times
        row["weighted"] = row["weighted"] or bool(weighted)
        row["extra"] = True

    # One row per session an exercise was logged in, which gives the
    # repetitions per date the heatmap is drawn from — summed when an exercise
    # landed twice on one day, possible across two sessions — the repetitions
    # per session the trend compares, and the weight per session the best one
    # is picked out of. That weight is
    # NULL for a session done with no extra weight, which is what keeps such a
    # session out of the running for `best_session`.
    per_date: dict[str, dict[date_type, int]] = {}
    per_session: dict[str, list[tuple[date_type, int, int]]] = {}
    best: dict[str, tuple[int, date_type, int]] = {}
    linked_sessions = (
        _filtered(
            db.session.query(
                Exercise.name,
                WorkoutSession.date,
                WorkoutSession.id,
                db.func.sum(SessionExercise.repetitions),
                db.func.sum(_WEIGHT_MOVED),
            )
            .join(SessionExercise, SessionExercise.exercise_id == Exercise.id)
            .join(WorkoutSession, WorkoutSession.id == SessionExercise.session_id),
            user_id,
            category,
        )
        .group_by(Exercise.name, WorkoutSession.id)
        .all()
    )
    extra_sessions = (
        _filtered(
            db.session.query(
                SessionExercise.extra_name,
                WorkoutSession.date,
                WorkoutSession.id,
                db.func.sum(SessionExercise.repetitions),
                db.func.sum(_WEIGHT_MOVED),
            )
            .join(WorkoutSession, WorkoutSession.id == SessionExercise.session_id)
            .filter(SessionExercise.exercise_id.is_(None)),
            user_id,
            category,
        )
        .group_by(SessionExercise.extra_name, WorkoutSession.id)
        .all()
    )
    for name, day, session_id, reps, weight in linked_sessions + extra_sessions:
        dates = per_date.setdefault(name, {})
        dates[day] = dates.get(day, 0) + int(reps or 0)
        per_session.setdefault(name, []).append((day, session_id, int(reps or 0)))
        if weight is None:
            continue  # bodyweight: repetitions only, nothing to be best at
        # Compared as a tuple, so a weight matched again is reported at the
        # later date rather than the first time it was reached.
        candidate = (int(weight), day, session_id)
        if candidate > best.get(name, (-1,)):
            best[name] = candidate

    for name, dates in per_date.items():
        row = bucket(name)
        row["heatmap"] = _calendar_weeks(dates, end, EXERCISE_HEATMAP_DAYS)
        row["trend"] = _repetition_trend(per_session[name])
        if name in best:  # absent for an exercise only ever done at bodyweight
            weight, day, _ = best[name]
            row["best_session"] = {"weight": weight, "date": day}

    for name, row in buckets.items():
        # Where the repetitions came from, or — for an exercise nobody has done
        # — the workouts it is waiting in.
        source = performed_in.get(name) if row["times"] else member_of.get(name)
        row["workouts"] = sorted(source or ())

    rows = list(buckets.values())
    if user_id is not None or category is not None:
        # Every exercise of every workout would otherwise show up on one
        # person's, or one sport's, page as a "Not performed yet" row. `times` is 0 for exactly
        # those, and is what leaves `heatmap` None.
        rows = [row for row in rows if row["times"]]
    return sorted(rows, key=lambda r: (-r["repetitions"], r["name"]))


def feeling_trend(
    end: date_type | None = None,
    days: int = TREND_DAYS,
    user_id: int | None = None,
    category: str | None = None,
) -> dict:
    """How the workouts of the last `days` days felt, one entry per day.

    Returns {"days": [...], "totals": {feeling: count}, "sessions": int,
    "start": date, "end": date}. Every day in the window gets an entry,
    oldest first:
    {"date": iso string, "sessions": int, "score": float | None,
     "feeling": one of FEELINGS or None, "counts": {feeling: int}}.
    Rest days have `sessions` 0, `score` None and `feeling` None. On a day with
    several sessions the score is their average and `feeling` is that average
    rounded half-up to the nearest feeling.
    """
    end = end or date_type.today()
    start = end - timedelta(days=days - 1)

    rows = (
        _filtered(
            db.session.query(
                WorkoutSession.date,
                WorkoutSession.feeling,
                db.func.count(WorkoutSession.id),
            ).filter(WorkoutSession.date >= start, WorkoutSession.date <= end),
            user_id,
            category,
        )
        .group_by(WorkoutSession.date, WorkoutSession.feeling)
        .all()
    )

    per_day: dict[date_type, dict[str, int]] = {}
    totals = {feeling: 0 for feeling in FEELINGS}
    for day, feeling, count in rows:
        per_day.setdefault(day, {})[feeling] = count
        totals[feeling] += count

    score_to_feeling = {score: feeling for feeling, score in FEELING_SCORES.items()}

    entries = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        counts = {feeling: per_day.get(day, {}).get(feeling, 0) for feeling in FEELINGS}
        sessions = sum(counts.values())
        if sessions:
            score = (
                sum(FEELING_SCORES[f] * n for f, n in counts.items()) / sessions
            )
            feeling = score_to_feeling[int(score + 0.5)]  # round half-up
        else:
            score, feeling = None, None
        entries.append(
            {
                "date": day.isoformat(),
                "sessions": sessions,
                "score": score,
                "feeling": feeling,
                "counts": counts,
            }
        )

    return {
        "days": entries,
        "totals": totals,
        "sessions": sum(totals.values()),
        "start": start,
        "end": end,
    }


def session_comments(
    user_id: int | None = None,
    limit: int = COMMENT_LIMIT,
    category: str | None = None,
) -> list[dict]:
    """The most recent sessions that carry a free-text note, newest first.

    Each entry is {"date": date, "workout": str, "feeling": str, "user": str,
    "comment": str}. Sessions without a comment are left out entirely, so this
    is a log of what was written rather than of what was tracked. Two sessions
    on one date are ordered newest-logged first, which the session id stands in
    for. `user` is carried on every entry so the across-everyone view can say
    who wrote the note; the per-user view already knows.

    At most `limit` entries come back — COMMENT_LIMIT of them by default, which
    is what the analytics page shows and names in its own copy. The cut is a SQL
    LIMIT applied after the ordering, so it keeps the newest notes rather than
    whichever the database happened to return first, and it is applied after
    `user_id` narrows the rows: picking a user lists their last `limit` notes,
    not their share of everyone's last `limit`.
    """
    rows = (
        _filtered(
            db.session.query(
                WorkoutSession.date,
                Workout.name,
                User.name,
                WorkoutSession.feeling,
                WorkoutSession.comment,
                WorkoutSession.id,
            )
            .join(Workout, Workout.id == WorkoutSession.workout_id)
            .join(User, User.id == WorkoutSession.user_id)
            .filter(WorkoutSession.comment.isnot(None)),
            user_id,
            category,
        )
        .order_by(WorkoutSession.date.desc(), WorkoutSession.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "date": day,
            "workout": workout,
            "user": user,
            "feeling": feeling,
            "comment": comment,
        }
        for day, workout, user, feeling, comment, _ in rows
    ]
