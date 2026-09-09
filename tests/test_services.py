from datetime import date, timedelta

import pytest

from src import services
from src.models import Movement, SessionMovement, Workout, WorkoutSession, db
from src.services import ValidationError


# ------------------------------------------------------------ create_workout


def test_create_workout_with_movements(app):
    workout = services.create_workout("Leg day", ["Squat", "Lunge"])
    assert workout.id is not None
    assert [m.name for m in workout.movements] == ["Squat", "Lunge"]
    assert Workout.query.count() == 1
    assert Movement.query.count() == 2


def test_create_workout_strips_and_drops_empty_movements(app):
    workout = services.create_workout("  Push day ", ["  Bench press ", "", "   "])
    assert workout.name == "Push day"
    assert [m.name for m in workout.movements] == ["Bench press"]


def test_create_workout_requires_name(app):
    with pytest.raises(ValidationError):
        services.create_workout("", ["Squat"])


def test_create_workout_requires_movements(app):
    with pytest.raises(ValidationError):
        services.create_workout("Leg day", ["", "  "])


def test_create_workout_rejects_duplicate_name(app):
    services.create_workout("Leg day", ["Squat"])
    with pytest.raises(ValidationError):
        services.create_workout("Leg day", ["Deadlift"])


def test_get_all_workouts_sorted_alphabetically(app):
    services.create_workout("Pull day", ["Row"])
    services.create_workout("Leg day", ["Squat"])
    assert [w.name for w in services.get_all_workouts()] == ["Leg day", "Pull day"]


def test_create_workout_drops_duplicate_movements(app):
    workout = services.create_workout("Leg day", ["Squat", "squat", " SQUAT ", "Lunge"])
    assert [m.name for m in workout.movements] == ["Squat", "Lunge"]


# ------------------------------------------------------- known_movement_names


def test_known_movement_names_empty_db(app):
    assert services.known_movement_names() == []


def test_known_movement_names_across_workouts_deduplicated(app):
    services.create_workout("Push day", ["Bench press", "Squat"])
    services.create_workout("Leg day", ["Squat", "Lunge"])
    assert services.known_movement_names() == ["Bench press", "Lunge", "Squat"]


def test_known_movement_names_sorted_case_insensitively(app):
    services.create_workout("Odd day", ["zebra walk", "Ape hang", "bear crawl"])
    assert services.known_movement_names() == ["Ape hang", "bear crawl", "zebra walk"]


def test_known_movement_names_includes_extras_logged_on_a_session(app):
    workout = services.create_workout("Leg day", ["Squat"])
    services.log_session(
        workout.id,
        date(2026, 9, 1),
        45,
        {workout.movements[0].id: 30},
        "good",
        extra_movements=[("Pull-up", 12)],
    )
    assert services.known_movement_names() == ["Pull-up", "Squat"]


# ---------------------------------------------------------------- log_session


@pytest.fixture()
def workout(app):
    """A workout with two movements, so per-movement repetitions matter."""
    return services.create_workout("Leg day", ["Squat", "Lunge"])


def reps_for(workout, *values):
    """Build a movement id -> repetitions mapping in movement order."""
    return {m.id: v for m, v in zip(workout.movements, values)}


def test_log_session_valid(app, workout):
    session = services.log_session(
        workout.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20), "good"
    )
    assert WorkoutSession.query.count() == 1
    assert session.workout.name == "Leg day"
    assert session.duration_minutes == 45
    assert session.feeling == "good"
    assert {log.movement.name: log.repetitions for log in session.logs} == {
        "Squat": 30,
        "Lunge": 20,
    }


def test_log_session_totals_repetitions_across_movements(app, workout):
    session = services.log_session(
        workout.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20), "good"
    )
    assert session.total_repetitions == 50


def test_log_session_requires_every_movement(app, workout):
    only_first = {workout.movements[0].id: 30}
    with pytest.raises(ValidationError, match="Lunge"):
        services.log_session(workout.id, date(2026, 9, 1), 45, only_first, "good")
    assert WorkoutSession.query.count() == 0
    assert SessionMovement.query.count() == 0


def test_log_session_ignores_movements_of_other_workouts(app, workout):
    other = services.create_workout("Push day", ["Bench press"])
    reps = reps_for(workout, 30, 20) | {other.movements[0].id: 99}
    session = services.log_session(workout.id, date(2026, 9, 1), 45, reps, "good")
    assert sorted(log.repetitions for log in session.logs) == [20, 30]


def test_log_session_unknown_workout(app):
    with pytest.raises(ValidationError):
        services.log_session(999, date.today(), 45, {}, "good")


@pytest.mark.parametrize("duration", [5, 9, 91, 120, 12])  # 12 not on 5-min grid
def test_log_session_invalid_duration(app, workout, duration):
    with pytest.raises(ValidationError):
        services.log_session(
            workout.id, date.today(), duration, reps_for(workout, 30, 20), "good"
        )


@pytest.mark.parametrize("reps", [-1, 121, 1000])
def test_log_session_invalid_repetitions(app, workout, reps):
    with pytest.raises(ValidationError):
        services.log_session(
            workout.id, date.today(), 45, reps_for(workout, 30, reps), "good"
        )
    assert WorkoutSession.query.count() == 0


@pytest.mark.parametrize("feeling", ["great", "terrible", "", "GOOD"])
def test_log_session_invalid_feeling(app, workout, feeling):
    with pytest.raises(ValidationError):
        services.log_session(
            workout.id, date.today(), 45, reps_for(workout, 30, 20), feeling
        )


@pytest.mark.parametrize("reps", [0, 1, 100, 120])
def test_log_session_accepts_the_whole_repetition_range(app, workout, reps):
    session = services.log_session(
        workout.id, date(2026, 9, 1), 45, reps_for(workout, reps, reps), "good"
    )
    assert [log.repetitions for log in session.logs] == [reps, reps]


def test_log_session_zero_repetitions_records_a_skipped_movement(app, workout):
    """0 is a real answer — the movement was part of the session but not done."""
    session = services.log_session(
        workout.id, date(2026, 9, 1), 45, reps_for(workout, 30, 0), "good"
    )
    assert {log.name: log.repetitions for log in session.logs} == {
        "Squat": 30,
        "Lunge": 0,
    }
    assert session.total_repetitions == 30


def test_log_session_accepts_a_zero_extra_movement(app, workout):
    session = services.log_session(
        workout.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        extra_movements=[("Pull-up", 0)],
    )
    extra = next(log for log in session.logs if log.is_extra)
    assert extra.repetitions == 0


def test_log_session_invalid_date_type(app, workout):
    with pytest.raises(ValidationError):
        services.log_session(
            workout.id, "2026-09-01", 45, reps_for(workout, 30, 20), "good"
        )


def test_deleting_workout_removes_its_session_logs(app, workout):
    services.log_session(
        workout.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20), "good"
    )
    db.session.delete(workout)
    db.session.commit()
    assert SessionMovement.query.count() == 0
    assert WorkoutSession.query.count() == 0


# ------------------------------------------------- log_session extra movements


def test_log_session_with_extra_movement(app, workout):
    session = services.log_session(
        workout.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        extra_movements=[("Pull-up", 12)],
    )
    assert {log.name: log.repetitions for log in session.logs} == {
        "Squat": 30,
        "Lunge": 20,
        "Pull-up": 12,
    }
    assert session.total_repetitions == 62
    extra = next(log for log in session.logs if log.is_extra)
    assert extra.movement_id is None
    assert extra.extra_name == "Pull-up"


def test_extra_movement_is_not_added_to_the_workout(app, workout):
    services.log_session(
        workout.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        extra_movements=[("Pull-up", 12)],
    )
    assert [m.name for m in workout.movements] == ["Squat", "Lunge"]
    assert Movement.query.count() == 2  # no Movement row created for the extra
    # ...so the next session is not asked for it again.
    session = services.log_session(
        workout.id, date(2026, 9, 2), 45, reps_for(workout, 10, 10), "good"
    )
    assert [log.name for log in session.logs] == ["Squat", "Lunge"]


def test_log_session_accepts_several_extra_movements(app, workout):
    session = services.log_session(
        workout.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        extra_movements=[("Pull-up", 12), ("Dip", 8)],
    )
    assert sorted(log.name for log in session.logs if log.is_extra) == ["Dip", "Pull-up"]


def test_log_session_strips_and_drops_blank_extra_movements(app, workout):
    session = services.log_session(
        workout.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        extra_movements=[("  Pull-up ", 12), ("", 10), ("   ", 10)],
    )
    assert [log.name for log in session.logs if log.is_extra] == ["Pull-up"]


def test_log_session_rejects_extra_that_is_already_in_the_workout(app, workout):
    with pytest.raises(ValidationError, match="already a movement"):
        services.log_session(
            workout.id,
            date(2026, 9, 1),
            45,
            reps_for(workout, 30, 20),
            "good",
            extra_movements=[("squat", 12)],  # case-insensitive
        )
    assert WorkoutSession.query.count() == 0


def test_log_session_rejects_duplicate_extra_movements(app, workout):
    with pytest.raises(ValidationError, match="only once"):
        services.log_session(
            workout.id,
            date(2026, 9, 1),
            45,
            reps_for(workout, 30, 20),
            "good",
            extra_movements=[("Pull-up", 12), ("pull-up", 8)],
        )
    assert WorkoutSession.query.count() == 0


@pytest.mark.parametrize("reps", [-1, 121, 1000])
def test_log_session_invalid_extra_repetitions(app, workout, reps):
    with pytest.raises(ValidationError, match="Pull-up"):
        services.log_session(
            workout.id,
            date(2026, 9, 1),
            45,
            reps_for(workout, 30, 20),
            "good",
            extra_movements=[("Pull-up", reps)],
        )
    assert WorkoutSession.query.count() == 0
    assert SessionMovement.query.count() == 0


def test_deleting_workout_removes_extra_movement_logs(app, workout):
    services.log_session(
        workout.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        extra_movements=[("Pull-up", 12)],
    )
    db.session.delete(workout)
    db.session.commit()
    assert SessionMovement.query.count() == 0


# --------------------------------------------------------------- date_choices


def test_date_choices_span_and_order():
    today = date(2026, 9, 8)
    choices = services.date_choices(days_back=30, today=today)
    assert len(choices) == 31
    assert choices[0] == today
    assert choices[-1] == today - timedelta(days=30)


def test_duration_and_repetition_choices_bounds():
    assert services.DURATION_CHOICES[0] == 10
    assert services.DURATION_CHOICES[-1] == 90
    assert services.REPETITION_CHOICES[0] == 0
    assert services.REPETITION_CHOICES[-1] == 120
    assert len(services.REPETITION_CHOICES) == 121
