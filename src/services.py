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
    User,
    Workout,
    WorkoutSession,
    db,
)

DURATION_CHOICES = list(range(10, 91, 5))  # 10-90 minutes
REPETITION_CHOICES = list(range(0, 121))  # 0-120, 0 meaning skipped
TREND_DAYS = 30  # window of the feeling graph on the analytics page
MOVEMENT_HEATMAP_DAYS = 365  # window of each per-movement heatmap
REPETITION_TREND_TOLERANCE = 0.15  # within ±15% counts as holding steady
MIN_AGE, MAX_AGE = 1, 120  # bounds of the age field, and of its error message
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
    user_id: int,
    session_date: date_type,
    duration_minutes: int,
    repetitions_by_movement: dict[int, int],
    feeling: str,
    extra_movements: list[tuple[str, int]] | None = None,
    comment: str = "",
) -> WorkoutSession:
    """Record a performed workout by one user, movement by movement.

    `repetitions_by_movement` maps movement id -> repetitions. Every movement of
    the workout must be present; ids belonging to other workouts are ignored,
    because the track form submits fields for all workouts when JS is off.

    `extra_movements` holds (name, repetitions) pairs for movements done in this
    session only. They are logged against the session without being added to the
    workout, so they never show up on the track form again. Pairs with a blank
    name are dropped, so an untouched row on the form is simply ignored.

    `comment` is a free-text note about the session. It is stripped, and a blank
    one is stored as NULL rather than an empty string, so `session_comments` can
    pick out the sessions that actually have something to say.
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
        user_id=user_id,
        date=session_date,
        duration_minutes=duration_minutes,
        feeling=feeling,
        comment=comment or None,
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


def _for_user(query, user_id: int | None):
    """Narrow a query that selects sessions down to one user.

    Every analytics function takes a `user_id`; None means "everyone", which is
    what the page shows until a user is picked from its dropdown. Apply this
    before grouping, so the filter lands in the WHERE clause.
    """
    if user_id is None:
        return query
    return query.filter(WorkoutSession.user_id == user_id)


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


def activity_map(
    end: date_type | None = None, days: int = 365, user_id: int | None = None
) -> dict:
    """GitHub-style activity data: one cell per day for the last `days` days.

    Cells count the sessions logged that day, by `user_id` or by everyone; see
    `_calendar_weeks` for the returned shape.
    """
    end = end or date_type.today()
    start = end - timedelta(days=days - 1)

    rows = (
        _for_user(
            db.session.query(
                WorkoutSession.date, db.func.count(WorkoutSession.id)
            ).filter(WorkoutSession.date >= start, WorkoutSession.date <= end),
            user_id,
        )
        .group_by(WorkoutSession.date)
        .all()
    )
    return _calendar_weeks({day: count for day, count in rows}, end, days)


def workout_frequency(user_id: int | None = None) -> list[dict]:
    """How often each workout has been done and how it felt, most frequent first.

    Each row is {"name": str, "count": int, "feelings": {feeling: count}}, with
    a `feelings` entry for every value in FEELINGS.

    Across everyone the table doubles as a list of what exists, so workouts
    never performed are included with a count of 0. For a single user those
    rows are just noise, so `user_id` lists only the workouts that user has
    actually performed — an inner join rather than an outer one.
    """
    on_workout = WorkoutSession.workout_id == Workout.id
    query = db.session.query(Workout.name, db.func.count(WorkoutSession.id))
    if user_id is None:
        query = query.outerjoin(WorkoutSession, on_workout)
    else:
        query = query.join(WorkoutSession, on_workout).filter(
            WorkoutSession.user_id == user_id
        )
    rows = query.group_by(Workout.id).all()
    by_feeling = (
        _for_user(
            db.session.query(
                Workout.name,
                WorkoutSession.feeling,
                db.func.count(WorkoutSession.id),
            ).join(WorkoutSession, WorkoutSession.workout_id == Workout.id),
            user_id,
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


def movement_repetitions(
    end: date_type | None = None, user_id: int | None = None
) -> list[dict]:
    """Repetitions per movement across every workout, most repetitions first.

    Movements are grouped by name, so a movement that appears in several
    workouts — or that was done once as an extra — is reported as a single row
    with its combined total.

    `workouts` names where the repetitions came from: the workouts of the
    sessions the movement was logged in, *not* every workout that has a movement
    of that name. An extra belongs to no workout, so one done only as an extra
    lists none, even when a workout the user never touched happens to contain a
    movement with the same name. For a movement nobody has performed there are
    no sessions to go on, so it falls back to the workouts it belongs to — the
    only thing there is to say about it. `extra` says whether the movement was
    ever logged as a session-only extra. Movements never performed are included
    with a total of 0.

    `trend` says whether its repetitions are going up, down or holding steady;
    see `_repetition_trend`. It reads the movement's whole history, not just the
    window drawn in `heatmap`.

    `heatmap` is the movement's history as a calendar grid of the last
    MOVEMENT_HEATMAP_DAYS days — the same shape as `activity_map`, but with each
    cell counting repetitions instead of sessions, shaded relative to that
    movement's own busiest day. Repetitions are summed when a movement was done
    more than once on a date, which can happen across two sessions.

    Filtering by `user_id` narrows the sessions counted *and* the movements
    listed: a movement that user has never performed is dropped rather than
    reported at 0, since the whole list would otherwise be padded with rows
    from workouts they have never touched. Without a `user_id` those rows stay,
    so the page doubles as a list of every movement that exists. A movement
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
                "times": 0,
                "workouts": [],
                "extra": False,
                "heatmap": None,
                "trend": _repetition_trend({}),
            },
        )

    # Movements that belong to a workout, whether or not they were ever done.
    # Membership alone does not earn a workout a place in `workouts` — see the
    # `performed_in` query below — but it is what gives a movement nobody has
    # done a row at all.
    member_of: dict[str, set[str]] = {}
    pairs = (
        db.session.query(Movement.name, Workout.name)
        .join(Workout, Movement.workout_id == Workout.id)
        .all()
    )
    for movement_name, workout_name in pairs:
        bucket(movement_name)
        member_of.setdefault(movement_name, set()).add(workout_name)

    # The workouts a movement's repetitions actually came from, taken from the
    # session each one was logged in. An extra contributes nothing here, which
    # is what keeps a movement done only as an extra from being labelled with
    # the workout that happens to have a movement of the same name.
    performed_in: dict[str, set[str]] = {}
    for movement_name, workout_name in _for_user(
        db.session.query(Movement.name, Workout.name)
        .join(SessionMovement, SessionMovement.movement_id == Movement.id)
        .join(WorkoutSession, WorkoutSession.id == SessionMovement.session_id)
        .join(Workout, Workout.id == WorkoutSession.workout_id),
        user_id,
    ).distinct():
        performed_in.setdefault(movement_name, set()).add(workout_name)

    logged = (
        _for_user(
            db.session.query(
                Movement.name,
                db.func.sum(SessionMovement.repetitions),
                db.func.count(SessionMovement.id),
            )
            .join(SessionMovement, SessionMovement.movement_id == Movement.id)
            .join(WorkoutSession, WorkoutSession.id == SessionMovement.session_id),
            user_id,
        )
        .group_by(Movement.name)
        .all()
    )
    for name, reps, times in logged:
        row = bucket(name)
        row["repetitions"] += int(reps or 0)
        row["times"] += times

    # Extras carry their own name instead of pointing at a movement row.
    extras = (
        _for_user(
            db.session.query(
                SessionMovement.extra_name,
                db.func.sum(SessionMovement.repetitions),
                db.func.count(SessionMovement.id),
            )
            .join(WorkoutSession, WorkoutSession.id == SessionMovement.session_id)
            .filter(SessionMovement.movement_id.is_(None)),
            user_id,
        )
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
        _for_user(
            db.session.query(
                Movement.name,
                WorkoutSession.date,
                db.func.sum(SessionMovement.repetitions),
            )
            .join(SessionMovement, SessionMovement.movement_id == Movement.id)
            .join(WorkoutSession, WorkoutSession.id == SessionMovement.session_id),
            user_id,
        )
        .group_by(Movement.name, WorkoutSession.date)
        .all()
    )
    extra_dates = (
        _for_user(
            db.session.query(
                SessionMovement.extra_name,
                WorkoutSession.date,
                db.func.sum(SessionMovement.repetitions),
            )
            .join(WorkoutSession, WorkoutSession.id == SessionMovement.session_id)
            .filter(SessionMovement.movement_id.is_(None)),
            user_id,
        )
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

    for name, row in buckets.items():
        # Where the repetitions came from, or — for a movement nobody has done
        # — the workouts it is waiting in.
        source = performed_in.get(name) if row["times"] else member_of.get(name)
        row["workouts"] = sorted(source or ())

    rows = list(buckets.values())
    if user_id is not None:
        # Every movement of every workout would otherwise show up on one
        # person's page as a "Not performed yet" row. `times` is 0 for exactly
        # those, and is what leaves `heatmap` None.
        rows = [row for row in rows if row["times"]]
    return sorted(rows, key=lambda r: (-r["repetitions"], r["name"]))


def feeling_trend(
    end: date_type | None = None,
    days: int = TREND_DAYS,
    user_id: int | None = None,
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
        _for_user(
            db.session.query(
                WorkoutSession.date,
                WorkoutSession.feeling,
                db.func.count(WorkoutSession.id),
            ).filter(WorkoutSession.date >= start, WorkoutSession.date <= end),
            user_id,
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


def session_comments(user_id: int | None = None) -> list[dict]:
    """The sessions that carry a free-text note, most recent first.

    Each entry is {"date": date, "workout": str, "feeling": str, "user": str,
    "comment": str}. Sessions without a comment are left out entirely, so this
    is a log of what was written rather than of what was tracked. Two sessions
    on one date are ordered newest-logged first, which the session id stands in
    for. `user` is carried on every entry so the across-everyone view can say
    who wrote the note; the per-user view already knows.
    """
    rows = (
        _for_user(
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
        )
        .order_by(WorkoutSession.date.desc(), WorkoutSession.id.desc())
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
