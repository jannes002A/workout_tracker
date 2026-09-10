from datetime import date, timedelta

import pytest

from src import services
from src.models import Exercise, SessionExercise, User, Workout, WorkoutSession, db
from src.services import ValidationError


# ---------------------------------------------------------------- create_user


def test_create_user(app):
    user = services.create_user("Alex", 34)
    assert user.id is not None
    assert (user.name, user.age) == ("Alex", 34)
    assert User.query.count() == 1


def test_create_user_strips_the_name(app):
    assert services.create_user("  Alex  ", 34).name == "Alex"


def test_create_user_requires_a_name(app):
    with pytest.raises(ValidationError, match="name is required"):
        services.create_user("   ", 34)
    assert User.query.count() == 0


@pytest.mark.parametrize("age", [0, -1, 121, "34", None])
def test_create_user_rejects_an_age_outside_the_range(app, age):
    with pytest.raises(ValidationError, match="between 1 and 120"):
        services.create_user("Alex", age)
    assert User.query.count() == 0


def test_create_user_accepts_the_ends_of_the_range(app):
    services.create_user("Youngest", services.MIN_AGE)
    services.create_user("Oldest", services.MAX_AGE)
    assert User.query.count() == 2


def test_create_user_rejects_a_duplicate_name_case_insensitively(app):
    services.create_user("Alex", 34)
    with pytest.raises(ValidationError, match="already exists"):
        services.create_user("  alex ", 41)
    assert User.query.count() == 1


def test_get_all_users_sorted_alphabetically(app):
    services.create_user("Sam", 41)
    services.create_user("Alex", 34)
    assert [u.name for u in services.get_all_users()] == ["Alex", "Sam"]


def test_get_all_users_empty_db(app):
    assert services.get_all_users() == []


def test_get_user(app, user):
    assert services.get_user(user.id) is user


def test_get_user_unknown_or_missing_id(app):
    assert services.get_user(999) is None
    assert services.get_user(None) is None


# ------------------------------------------------------------ create_workout


def test_create_workout_with_exercises(app):
    workout = services.create_workout("Leg day", ["Squat", "Lunge"])
    assert workout.id is not None
    assert [m.name for m in workout.exercises] == ["Squat", "Lunge"]
    assert Workout.query.count() == 1
    assert Exercise.query.count() == 2


def test_create_workout_strips_and_drops_empty_exercises(app):
    workout = services.create_workout("  Push day ", ["  Bench press ", "", "   "])
    assert workout.name == "Push day"
    assert [m.name for m in workout.exercises] == ["Bench press"]


def test_create_workout_requires_name(app):
    with pytest.raises(ValidationError):
        services.create_workout("", ["Squat"])


def test_create_workout_requires_exercises(app):
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


def test_create_workout_drops_duplicate_exercises(app):
    workout = services.create_workout("Leg day", ["Squat", "squat", " SQUAT ", "Lunge"])
    assert [m.name for m in workout.exercises] == ["Squat", "Lunge"]


# ------------------------------------------------------- known_exercise_names


def test_known_exercise_names_empty_db(app):
    assert services.known_exercise_names() == []


def test_known_exercise_names_across_workouts_deduplicated(app):
    services.create_workout("Push day", ["Bench press", "Squat"])
    services.create_workout("Leg day", ["Squat", "Lunge"])
    assert services.known_exercise_names() == ["Bench press", "Lunge", "Squat"]


def test_known_exercise_names_sorted_case_insensitively(app):
    services.create_workout("Odd day", ["zebra walk", "Ape hang", "bear crawl"])
    assert services.known_exercise_names() == ["Ape hang", "bear crawl", "zebra walk"]


def test_known_exercise_names_includes_extras_logged_on_a_session(app, user):
    workout = services.create_workout("Leg day", ["Squat"])
    services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        {workout.exercises[0].id: 30},
        "good",
        extra_exercises=[("Pull-up", 12)],
    )
    assert services.known_exercise_names() == ["Pull-up", "Squat"]


# ---------------------------------------------------------------- log_session


@pytest.fixture()
def workout(app):
    """A workout with two exercises, so per-exercise repetitions matter."""
    return services.create_workout("Leg day", ["Squat", "Lunge"])


def reps_for(workout, *values):
    """Build an exercise id -> repetitions mapping in exercise order."""
    return {m.id: v for m, v in zip(workout.exercises, values)}


def test_log_session_valid(app, workout, user):
    session = services.log_session(
        workout.id,
        user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20), "good"
    )
    assert WorkoutSession.query.count() == 1
    assert session.workout.name == "Leg day"
    assert session.duration_minutes == 45
    assert session.feeling == "good"
    assert {log.exercise.name: log.repetitions for log in session.logs} == {
        "Squat": 30,
        "Lunge": 20,
    }


def test_log_session_totals_repetitions_across_exercises(app, workout, user):
    session = services.log_session(
        workout.id,
        user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20), "good"
    )
    assert session.total_repetitions == 50


def test_log_session_requires_every_exercise(app, workout, user):
    only_first = {workout.exercises[0].id: 30}
    with pytest.raises(ValidationError, match="Lunge"):
        services.log_session(workout.id, user.id, date(2026, 9, 1), 45, only_first, "good")
    assert WorkoutSession.query.count() == 0
    assert SessionExercise.query.count() == 0


def test_log_session_ignores_exercises_of_other_workouts(app, workout, user):
    other = services.create_workout("Push day", ["Bench press"])
    reps = reps_for(workout, 30, 20) | {other.exercises[0].id: 99}
    session = services.log_session(workout.id, user.id, date(2026, 9, 1), 45, reps, "good")
    assert sorted(log.repetitions for log in session.logs) == [20, 30]


def test_log_session_unknown_workout(app, user):
    with pytest.raises(ValidationError):
        services.log_session(999, user.id, date.today(), 45, {}, "good")


def test_log_session_records_the_user(app, workout, user):
    session = services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20), "good"
    )
    assert session.user is user
    assert user.sessions == [session]


def test_log_session_stores_a_comment(app, workout, user):
    session = services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20),
        "good", comment="  Felt strong.  ",
    )
    assert session.comment == "Felt strong."


def test_log_session_without_a_comment_stores_null(app, workout, user):
    """NULL rather than "", so session_comments can pick the ones worth showing."""
    session = services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20), "good"
    )
    assert session.comment is None


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
def test_log_session_blank_comment_stores_null(app, workout, user, blank):
    session = services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20),
        "good", comment=blank,
    )
    assert session.comment is None


def test_log_session_keeps_the_line_breaks_of_a_comment(app, workout, user):
    session = services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20),
        "good", comment="Felt strong.\nKnee fine.",
    )
    assert session.comment == "Felt strong.\nKnee fine."


def test_log_session_rejects_an_over_long_comment(app, workout, user):
    too_long = "x" * (services.MAX_COMMENT_LENGTH + 1)
    with pytest.raises(ValidationError, match="2000 characters"):
        services.log_session(
            workout.id, user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20),
            "good", comment=too_long,
        )
    assert WorkoutSession.query.count() == 0


def test_log_session_accepts_a_comment_at_the_limit(app, workout, user):
    at_limit = "x" * services.MAX_COMMENT_LENGTH
    session = services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20),
        "good", comment=at_limit,
    )
    assert session.comment == at_limit


def test_log_session_unknown_user(app, workout):
    with pytest.raises(ValidationError, match="user that exists"):
        services.log_session(
            workout.id, 999, date.today(), 45, reps_for(workout, 30, 20), "good"
        )
    assert WorkoutSession.query.count() == 0


def test_deleting_a_user_deletes_their_sessions(app, workout, user):
    services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20), "good"
    )
    db.session.delete(user)
    db.session.commit()
    assert WorkoutSession.query.count() == 0
    assert SessionExercise.query.count() == 0
    assert Workout.query.count() == 1  # the template itself is shared, and stays


@pytest.mark.parametrize("duration", [5, 9, 91, 120, 12])  # 12 not on 5-min grid
def test_log_session_invalid_duration(app, workout, duration, user):
    with pytest.raises(ValidationError):
        services.log_session(
            workout.id,
            user.id, date.today(), duration, reps_for(workout, 30, 20), "good"
        )


@pytest.mark.parametrize("reps", [-1, 121, 1000])
def test_log_session_invalid_repetitions(app, workout, reps, user):
    with pytest.raises(ValidationError):
        services.log_session(
            workout.id,
            user.id, date.today(), 45, reps_for(workout, 30, reps), "good"
        )
    assert WorkoutSession.query.count() == 0


@pytest.mark.parametrize("feeling", ["great", "terrible", "", "GOOD"])
def test_log_session_invalid_feeling(app, workout, feeling, user):
    with pytest.raises(ValidationError):
        services.log_session(
            workout.id,
            user.id, date.today(), 45, reps_for(workout, 30, 20), feeling
        )


@pytest.mark.parametrize("reps", [0, 1, 100, 120])
def test_log_session_accepts_the_whole_repetition_range(app, workout, reps, user):
    session = services.log_session(
        workout.id,
        user.id, date(2026, 9, 1), 45, reps_for(workout, reps, reps), "good"
    )
    assert [log.repetitions for log in session.logs] == [reps, reps]


def test_log_session_zero_repetitions_records_a_skipped_exercise(app, workout, user):
    """0 is a real answer — the exercise was part of the session but not done."""
    session = services.log_session(
        workout.id,
        user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 0), "good"
    )
    assert {log.name: log.repetitions for log in session.logs} == {
        "Squat": 30,
        "Lunge": 0,
    }
    assert session.total_repetitions == 30


def test_log_session_accepts_a_zero_extra_exercise(app, workout, user):
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        extra_exercises=[("Pull-up", 0)],
    )
    extra = next(log for log in session.logs if log.is_extra)
    assert extra.repetitions == 0


def test_log_session_invalid_date_type(app, workout, user):
    with pytest.raises(ValidationError):
        services.log_session(
            workout.id,
            user.id, "2026-09-01", 45, reps_for(workout, 30, 20), "good"
        )


def test_deleting_workout_removes_its_session_logs(app, workout, user):
    services.log_session(
        workout.id,
        user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20), "good"
    )
    db.session.delete(workout)
    db.session.commit()
    assert SessionExercise.query.count() == 0
    assert WorkoutSession.query.count() == 0


# ------------------------------------------------- log_session extra exercises


def test_log_session_with_extra_exercise(app, workout, user):
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        extra_exercises=[("Pull-up", 12)],
    )
    assert {log.name: log.repetitions for log in session.logs} == {
        "Squat": 30,
        "Lunge": 20,
        "Pull-up": 12,
    }
    assert session.total_repetitions == 62
    extra = next(log for log in session.logs if log.is_extra)
    assert extra.exercise_id is None
    assert extra.extra_name == "Pull-up"


def test_extra_exercise_is_not_added_to_the_workout(app, workout, user):
    services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        extra_exercises=[("Pull-up", 12)],
    )
    assert [m.name for m in workout.exercises] == ["Squat", "Lunge"]
    assert Exercise.query.count() == 2  # no Exercise row created for the extra
    # ...so the next session is not asked for it again.
    session = services.log_session(
        workout.id,
        user.id, date(2026, 9, 2), 45, reps_for(workout, 10, 10), "good"
    )
    assert [log.name for log in session.logs] == ["Squat", "Lunge"]


def test_log_session_accepts_several_extra_exercises(app, workout, user):
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        extra_exercises=[("Pull-up", 12), ("Dip", 8)],
    )
    assert sorted(log.name for log in session.logs if log.is_extra) == ["Dip", "Pull-up"]


def test_log_session_strips_and_drops_blank_extra_exercises(app, workout, user):
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        extra_exercises=[("  Pull-up ", 12), ("", 10), ("   ", 10)],
    )
    assert [log.name for log in session.logs if log.is_extra] == ["Pull-up"]


def test_log_session_rejects_extra_that_is_already_in_the_workout(app, workout, user):
    with pytest.raises(ValidationError, match="already an exercise"):
        services.log_session(
            workout.id,
            user.id,
            date(2026, 9, 1),
            45,
            reps_for(workout, 30, 20),
            "good",
            extra_exercises=[("squat", 12)],  # case-insensitive
        )
    assert WorkoutSession.query.count() == 0


def test_log_session_rejects_duplicate_extra_exercises(app, workout, user):
    with pytest.raises(ValidationError, match="only once"):
        services.log_session(
            workout.id,
            user.id,
            date(2026, 9, 1),
            45,
            reps_for(workout, 30, 20),
            "good",
            extra_exercises=[("Pull-up", 12), ("pull-up", 8)],
        )
    assert WorkoutSession.query.count() == 0


@pytest.mark.parametrize("reps", [-1, 121, 1000])
def test_log_session_invalid_extra_repetitions(app, workout, reps, user):
    with pytest.raises(ValidationError, match="Pull-up"):
        services.log_session(
            workout.id,
            user.id,
            date(2026, 9, 1),
            45,
            reps_for(workout, 30, 20),
            "good",
            extra_exercises=[("Pull-up", reps)],
        )
    assert WorkoutSession.query.count() == 0
    assert SessionExercise.query.count() == 0


def test_deleting_workout_removes_extra_exercise_logs(app, workout, user):
    services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        extra_exercises=[("Pull-up", 12)],
    )
    db.session.delete(workout)
    db.session.commit()
    assert SessionExercise.query.count() == 0


# --------------------------------------------------------------- date_choices


# ------------------------------------------------- log_session: extra weight


def weights_for(workout, *values):
    """Build an exercise id -> extra weight mapping in exercise order."""
    return {m.id: v for m, v in zip(workout.exercises, values)}


def test_log_session_records_the_weight_per_exercise(app, workout, user):
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        weights_by_exercise=weights_for(workout, 60, 25),
    )
    assert {log.name: log.weight for log in session.logs} == {
        "Squat": 60,
        "Lunge": 25,
    }


def test_log_session_defaults_a_missing_weight_to_the_lowest_choice(app, workout, user):
    """The weight is optional per exercise, unlike the repetitions."""
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        weights_by_exercise={workout.exercises[0].id: 60},
    )
    assert {log.name: log.weight for log in session.logs} == {
        "Squat": 60,
        "Lunge": services.DEFAULT_WEIGHT,
    }
    assert services.DEFAULT_WEIGHT == 1


def test_log_session_without_any_weights_uses_the_default(app, workout, user):
    session = services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20), "good"
    )
    assert [log.weight for log in session.logs] == [1, 1]


@pytest.mark.parametrize("weight", [0, -1, 201, 1000])
def test_log_session_invalid_weight(app, workout, weight, user):
    with pytest.raises(ValidationError, match="between 1 and 200"):
        services.log_session(
            workout.id,
            user.id,
            date.today(),
            45,
            reps_for(workout, 30, 20),
            "good",
            weights_by_exercise=weights_for(workout, 20, weight),
        )
    assert WorkoutSession.query.count() == 0


def test_log_session_invalid_weight_names_the_exercise(app, workout, user):
    with pytest.raises(ValidationError, match="Weight for 'Lunge'"):
        services.log_session(
            workout.id,
            user.id,
            date.today(),
            45,
            reps_for(workout, 30, 20),
            "good",
            weights_by_exercise=weights_for(workout, 20, 500),
        )


@pytest.mark.parametrize("weight", [1, 100, 200])
def test_log_session_accepts_the_whole_weight_range(app, workout, weight, user):
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        weights_by_exercise=weights_for(workout, weight, weight),
    )
    assert [log.weight for log in session.logs] == [weight, weight]


def test_log_session_ignores_the_weights_of_other_workouts_exercises(app, workout, user):
    """Without JS the track form submits every workout's weight fields too."""
    other = services.create_workout("Push day", ["Bench press"])
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        weights_by_exercise=weights_for(workout, 60, 25)
        | {other.exercises[0].id: 999},
    )
    assert sorted(log.weight for log in session.logs) == [25, 60]


def test_log_session_records_the_weight_of_an_extra_exercise(app, workout, user):
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        extra_exercises=[("Pull-up", 12, 15)],
    )
    pull_up = next(log for log in session.logs if log.name == "Pull-up")
    assert pull_up.weight == 15


def test_log_session_extra_exercise_without_a_weight_uses_the_default(
    app, workout, user
):
    """A pair rather than a triple, which is all a caller has to pass."""
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        extra_exercises=[("Pull-up", 12)],
    )
    pull_up = next(log for log in session.logs if log.name == "Pull-up")
    assert pull_up.weight == services.DEFAULT_WEIGHT


@pytest.mark.parametrize("weight", [0, -1, 201])
def test_log_session_invalid_extra_weight(app, workout, weight, user):
    with pytest.raises(ValidationError, match="Weight for 'Pull-up'"):
        services.log_session(
            workout.id,
            user.id,
            date.today(),
            45,
            reps_for(workout, 30, 20),
            "good",
            extra_exercises=[("Pull-up", 12, weight)],
        )
    assert WorkoutSession.query.count() == 0


def test_weight_moved_is_the_weight_once_per_repetition(app, workout, user):
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        weights_by_exercise=weights_for(workout, 60, 25),
    )
    assert {log.name: log.weight_moved for log in session.logs} == {
        "Squat": 1800,  # 30 x 60
        "Lunge": 500,  # 20 x 25
    }


def test_weight_moved_is_zero_for_a_exercise_not_done(app, workout, user):
    """0 repetitions moved nothing, however heavy the weight picked was."""
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 0),
        "good",
        weights_by_exercise=weights_for(workout, 60, 100),
    )
    lunge = next(log for log in session.logs if log.name == "Lunge")
    assert lunge.weight_moved == 0


def test_session_total_weight_sums_every_exercise(app, workout, user):
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        weights_by_exercise=weights_for(workout, 60, 25),
        extra_exercises=[("Pull-up", 10, 5)],
    )
    assert session.total_weight == 1800 + 500 + 50


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


def test_weight_choices_bounds_and_default():
    assert services.WEIGHT_CHOICES[0] == 1
    assert services.WEIGHT_CHOICES[-1] == 200
    assert len(services.WEIGHT_CHOICES) == 200
    assert services.DEFAULT_WEIGHT == services.WEIGHT_CHOICES[0]
