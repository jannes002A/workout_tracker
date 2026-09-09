"""Core application logic.

Every function here is covered by a test in the tests/ folder.
Keeping logic out of the route handlers makes it easy to test without HTTP.
"""

import math
from datetime import date as date_type
from datetime import timedelta

from src.models import (
    FEELING_SCORES,
    FEELINGS,
    Movement,
    SessionMovement,
    Workout,
    WorkoutSession,
    db,
)

DURATION_CHOICES = list(range(10, 91, 5))  # 10-90 minutes
REPETITION_CHOICES = list(range(0, 121))  # 0-120, 0 meaning skipped
TREND_DAYS = 30  # window of the feeling graph on the analytics page
MOVEMENT_HEATMAP_DAYS = 365  # window of each per-movement heatmap
REPETITION_TREND_TOLERANCE = 0.15  # within ±15% counts as holding steady


class ValidationError(ValueError):
    """Raised when user input is invalid."""


# ---------------------------------------------------------------- workouts


def create_workout(name: str, movement_names: list[str]) -> Workout:
    """Create a workout with its movements. Empty movement names are dropped."""
    name = (name or "").strip()
    movements, seen = [], set()
    for raw in movement_names:
        movement = (raw or "").strip()
        if not movement or movement.casefold() in seen:
            continue  # blank field, or the same movement picked twice
        seen.add(movement.casefold())
        movements.append(movement)
    if not name:
        raise ValidationError("Workout name is required.")
    if not movements:
        raise ValidationError("Add at least one movement.")
    if Workout.query.filter_by(name=name).first():
        raise ValidationError(f"A workout named '{name}' already exists.")

    workout = Workout(name=name)
    workout.movements = [Movement(name=m) for m in movements]
    db.session.add(workout)
    db.session.commit()
    return workout


def get_all_workouts() -> list[Workout]:
    """All workouts, alphabetically."""
    return Workout.query.order_by(Workout.name).all()


def known_movement_names() -> list[str]:
    """Every movement name already in the log, sorted case-insensitively.

    Covers the movements of existing workouts as well as extras logged on the
    track page, so the create page can offer any of them for reuse.
    """
    names = {name for (name,) in db.session.query(Movement.name).distinct()}
    extras = (
        db.session.query(SessionMovement.extra_name)
        .filter(SessionMovement.movement_id.is_(None))
        .distinct()
    )
    names |= {name for (name,) in extras if name}
    return sorted(names, key=str.casefold)


# ---------------------------------------------------------------- sessions


def log_session(
    workout_id: int,
    session_date: date_type,
    duration_minutes: int,
    repetitions_by_movement: dict[int, int],
    feeling: str,
    extra_movements: list[tuple[str, int]] | None = None,
) -> WorkoutSession:
    """Record a performed workout, with repetitions for each of its movements.

    `repetitions_by_movement` maps movement id -> repetitions. Every movement of
    the workout must be present; ids belonging to other workouts are ignored,
    because the track form submits fields for all workouts when JS is off.

    `extra_movements` holds (name, repetitions) pairs for movements done in this
    session only. They are logged against the session without being added to the
    workout, so they never show up on the track form again. Pairs with a blank
    name are dropped, so an untouched row on the form is simply ignored.
    """
    workout = db.session.get(Workout, workout_id)
    if not workout:
        raise ValidationError("Select a workout that exists.")
    if duration_minutes not in DURATION_CHOICES:
        raise ValidationError("Duration must be between 10 and 90 minutes.")
    if feeling not in FEELINGS:
        raise ValidationError("Feeling must be good, okay or bad.")
    if not isinstance(session_date, date_type):
        raise ValidationError("Invalid date.")

    provided = repetitions_by_movement or {}
    logs = []
    for movement in workout.movements:
        if movement.id not in provided:
            raise ValidationError(f"Enter repetitions for '{movement.name}'.")
        reps = provided[movement.id]
        if reps not in REPETITION_CHOICES:
            raise ValidationError(
                f"Repetitions for '{movement.name}' must be between "
                f"{REPETITION_CHOICES[0]} and {REPETITION_CHOICES[-1]}."
            )
        logs.append(SessionMovement(movement_id=movement.id, repetitions=reps))

    of_workout = {movement.name.casefold() for movement in workout.movements}
    seen_extras: set[str] = set()
    for name, reps in extra_movements or []:
        name = (name or "").strip()
        if not name:
            continue  # an untouched extra-movement row on the form
        if name.casefold() in of_workout:
            raise ValidationError(
                f"'{name}' is already a movement of {workout.name} — "
                "set its repetitions above."
            )
        if name.casefold() in seen_extras:
            raise ValidationError(f"Add the extra movement '{name}' only once.")
        if reps not in REPETITION_CHOICES:
            raise ValidationError(
                f"Repetitions for '{name}' must be between "
                f"{REPETITION_CHOICES[0]} and {REPETITION_CHOICES[-1]}."
            )
        seen_extras.add(name.casefold())
        logs.append(SessionMovement(extra_name=name, repetitions=reps))

    session = WorkoutSession(
        workout_id=workout_id,
        date=session_date,
        duration_minutes=duration_minutes,
        feeling=feeling,
    )
    session.logs = logs
    db.session.add(session)
    db.session.commit()
    return session


def date_choices(days_back: int = 30, today: date_type | None = None) -> list[date_type]:
    """Dates for the date dropdown: today plus the previous `days_back` days."""
    today = today or date_type.today()
    return [today - timedelta(days=i) for i in range(days_back + 1)]


# ---------------------------------------------------------------- analytics


def _calendar_weeks(
    counts: dict[date_type, int], end: date_type, days: int
) -> dict:
    """Bucket per-day counts into a GitHub-style grid of Monday-first weeks.

    Returns {"weeks": [[cell, ...] x7 per week], "max": int, "months": [...]}
    where each cell is {"date": iso string, "count": int, "level": 0-4} or None
    for the padding days before the window starts. Levels are relative to the
    busiest day, and counts outside the window are ignored.

    `months` labels the x axis: one {"label": "Sep 2025", "weeks": int} per run
    of week columns, so the labels can be laid out above the grid. A week is
    attributed to the month of its first day, so a label sits above the first
    week that starts in that month. Their `weeks` sum to the number of columns.
    """
    start = end - timedelta(days=days - 1)
    counts = {day: count for day, count in counts.items() if start <= day <= end}
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
            {"date": current.isoformat(), "count": count, "level": level(count)}
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


def _repetition_trend(dates: dict[date_type, int]) -> dict:
    """Whether a movement's repetitions are going up, going down or holding.

    Splits the movement's own history — the span from the first date it was
    performed to the last — into two halves of equal length and compares the
    repetitions done in each. Returns
    {"direction": "up" | "down" | "similar" | None, "early": int, "late": int,
     "change": float | None, "split": iso string | None}, where `change` is the
    fraction the later half differs by (0.5 being +50%) and `split` is the last
    date counted as early.

    `direction` is None when everything falls on a single date, which is too
    little to read a trend from. A change within REPETITION_TREND_TOLERANCE
    either way counts as "similar". For an even span the earlier half takes the
    middle day. `change` is None when the earlier half is 0, since there is no
    baseline to be a percentage of.
    """
    nothing = {"direction": None, "early": 0, "late": 0, "change": None, "split": None}
    if not dates:
        return nothing

    first, last = min(dates), max(dates)
    span = (last - first).days
    if span == 0:
        return nothing

    split = first + timedelta(days=span // 2)
    early = sum(reps for day, reps in dates.items() if day <= split)
    late = sum(reps for day, reps in dates.items() if day > split)

    if early == 0:
        direction, change = ("up" if late > 0 else "similar"), None
    else:
        change = (late - early) / early
        if abs(change) <= REPETITION_TREND_TOLERANCE:
            direction = "similar"
        else:
            direction = "up" if change > 0 else "down"

    return {
        "direction": direction,
        "early": early,
        "late": late,
        "change": change,
        "split": split.isoformat(),
    }


def activity_map(end: date_type | None = None, days: int = 365) -> dict:
    """GitHub-style activity data: one cell per day for the last `days` days.

    Cells count the sessions logged that day; see `_calendar_weeks` for the
    returned shape.
    """
    end = end or date_type.today()
    start = end - timedelta(days=days - 1)

    rows = (
        db.session.query(WorkoutSession.date, db.func.count(WorkoutSession.id))
        .filter(WorkoutSession.date >= start, WorkoutSession.date <= end)
        .group_by(WorkoutSession.date)
        .all()
    )
    return _calendar_weeks({day: count for day, count in rows}, end, days)


def workout_frequency() -> list[dict]:
    """How often each workout has been done and how it felt, most frequent first.

    Each row is {"name": str, "count": int, "feelings": {feeling: count}}, with
    a `feelings` entry for every value in FEELINGS. Workouts never performed are
    included with a count of 0.
    """
    rows = (
        db.session.query(Workout.name, db.func.count(WorkoutSession.id))
        .outerjoin(WorkoutSession)
        .group_by(Workout.id)
        .all()
    )
    by_feeling = (
        db.session.query(
            Workout.name, WorkoutSession.feeling, db.func.count(WorkoutSession.id)
        )
        .join(WorkoutSession, WorkoutSession.workout_id == Workout.id)
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


def movement_repetitions(end: date_type | None = None) -> list[dict]:
    """Repetitions per movement across every workout, most repetitions first.

    Movements are grouped by name, so a movement that appears in several
    workouts — or that was done once as an extra — is reported as a single row
    with its combined total. `workouts` lists the workouts the movement belongs
    to and `extra` says whether it was ever logged as a session-only extra.
    Movements never performed are included with a total of 0.

    `trend` says whether its repetitions are going up, down or holding steady;
    see `_repetition_trend`. It reads the movement's whole history, not just the
    window drawn in `heatmap`.

    `heatmap` is the movement's history as a calendar grid of the last
    MOVEMENT_HEATMAP_DAYS days — the same shape as `activity_map`, but with each
    cell counting repetitions instead of sessions, shaded relative to that
    movement's own busiest day. Repetitions are summed when a movement was done
    more than once on a date, which can happen across two sessions.
    """
    end = end or date_type.today()
    buckets: dict[str, dict] = {}

    def bucket(name: str) -> dict:
        return buckets.setdefault(
            name,
            {
                "name": name,
                "repetitions": 0,
                "times": 0,
                "workouts": [],
                "extra": False,
                "heatmap": None,
                "trend": _repetition_trend({}),
            },
        )

    # Movements that belong to a workout, whether or not they were ever done.
    pairs = (
        db.session.query(Movement.name, Workout.name)
        .join(Workout, Movement.workout_id == Workout.id)
        .all()
    )
    for movement_name, workout_name in pairs:
        workouts = bucket(movement_name)["workouts"]
        if workout_name not in workouts:
            workouts.append(workout_name)

    logged = (
        db.session.query(
            Movement.name,
            db.func.sum(SessionMovement.repetitions),
            db.func.count(SessionMovement.id),
        )
        .join(SessionMovement, SessionMovement.movement_id == Movement.id)
        .group_by(Movement.name)
        .all()
    )
    for name, reps, times in logged:
        row = bucket(name)
        row["repetitions"] += int(reps or 0)
        row["times"] += times

    # Extras carry their own name instead of pointing at a movement row.
    extras = (
        db.session.query(
            SessionMovement.extra_name,
            db.func.sum(SessionMovement.repetitions),
            db.func.count(SessionMovement.id),
        )
        .filter(SessionMovement.movement_id.is_(None))
        .group_by(SessionMovement.extra_name)
        .all()
    )
    for name, reps, times in extras:
        row = bucket(name)
        row["repetitions"] += int(reps or 0)
        row["times"] += times
        row["extra"] = True

    # Repetitions per date, so each movement can be drawn as a heatmap.
    per_date: dict[str, dict[date_type, int]] = {}
    linked_dates = (
        db.session.query(
            Movement.name,
            WorkoutSession.date,
            db.func.sum(SessionMovement.repetitions),
        )
        .join(SessionMovement, SessionMovement.movement_id == Movement.id)
        .join(WorkoutSession, WorkoutSession.id == SessionMovement.session_id)
        .group_by(Movement.name, WorkoutSession.date)
        .all()
    )
    extra_dates = (
        db.session.query(
            SessionMovement.extra_name,
            WorkoutSession.date,
            db.func.sum(SessionMovement.repetitions),
        )
        .join(WorkoutSession, WorkoutSession.id == SessionMovement.session_id)
        .filter(SessionMovement.movement_id.is_(None))
        .group_by(SessionMovement.extra_name, WorkoutSession.date)
        .all()
    )
    for name, day, reps in linked_dates + extra_dates:
        dates = per_date.setdefault(name, {})
        dates[day] = dates.get(day, 0) + int(reps or 0)

    for name, dates in per_date.items():
        row = bucket(name)
        row["heatmap"] = _calendar_weeks(dates, end, MOVEMENT_HEATMAP_DAYS)
        row["trend"] = _repetition_trend(dates)

    for row in buckets.values():
        row["workouts"].sort()
    return sorted(buckets.values(), key=lambda r: (-r["repetitions"], r["name"]))


def feeling_trend(end: date_type | None = None, days: int = TREND_DAYS) -> dict:
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
        db.session.query(
            WorkoutSession.date,
            WorkoutSession.feeling,
            db.func.count(WorkoutSession.id),
        )
        .filter(WorkoutSession.date >= start, WorkoutSession.date <= end)
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
