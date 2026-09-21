from datetime import date, timedelta

import pytest

from src import services
from src.models import (
    CATEGORY_PALETTE,
    DEFAULT_CATEGORIES,
    DEFAULT_CATEGORY,
    Category,
    Exercise,
    SessionExercise,
    User,
    Workout,
    WorkoutSession,
    db,
)
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


# --------------------------------------------------------------- categories


def test_a_fresh_database_comes_with_the_default_sorts_of_sport(app):
    """create_app seeds them, so the create page opens with a full dropdown."""
    assert [(c.value, c.label, c.color) for c in services.get_all_categories()] == [
        *DEFAULT_CATEGORIES
    ]


def test_ensure_categories_is_safe_to_run_again(app):
    services.create_category("Running")
    services.ensure_categories()
    assert Category.query.count() == len(DEFAULT_CATEGORIES) + 1
    assert [c.label for c in services.get_all_categories()][-1] == "Running"


def test_ensure_categories_puts_a_missing_default_back_at_the_end(app):
    """Deleting one and re-seeding must not disturb the sorts already there."""
    db.session.delete(services.category_map()["judo"])
    db.session.commit()
    services.ensure_categories()
    assert [c.value for c in services.get_all_categories()] == [
        "weights",
        "mobility",
        "other",
        "judo",
    ]


def test_category_map_is_keyed_by_value_in_order(app):
    assert list(services.category_map()) == [v for v, _, _ in DEFAULT_CATEGORIES]
    assert services.category_map()["judo"].label == "Judo"


def test_category_labels_are_in_order(app):
    assert services.category_labels() == [label for _, label, _ in DEFAULT_CATEGORIES]


def test_create_category_adds_a_sort_of_sport_at_the_end(app):
    category = services.create_category("  Running  ")
    assert (category.value, category.label) == ("running", "Running")
    assert services.get_all_categories()[-1].id == category.id


def test_create_category_reduces_the_label_to_a_value(app):
    assert services.create_category("Trail running!").value == "trail-running"


def test_create_category_takes_the_first_unused_palette_colour(app):
    first = services.create_category("Running")
    second = services.create_category("Cycling")
    assert (first.color, second.color) == CATEGORY_PALETTE[:2]
    # and never one of the colours the seeded sorts of sport already wear
    seeded = {color for _, _, color in DEFAULT_CATEGORIES}
    assert not seeded & {first.color, second.color}


def test_create_category_reuses_the_palette_once_it_runs_out(app):
    for i in range(len(CATEGORY_PALETTE)):
        services.create_category(f"Sport {i}")
    assert services.create_category("One more").color in CATEGORY_PALETTE


def test_create_category_requires_a_name(app):
    with pytest.raises(ValidationError, match="Name the sort of sport"):
        services.create_category("   ")
    assert Category.query.count() == len(DEFAULT_CATEGORIES)


def test_create_category_rejects_a_name_of_punctuation_alone(app):
    with pytest.raises(ValidationError, match="letter or number"):
        services.create_category("!!!")


def test_create_category_rejects_too_long_a_name(app):
    with pytest.raises(ValidationError, match="characters"):
        services.create_category("x" * (services.MAX_CATEGORY_LABEL + 1))


def test_create_category_rejects_a_duplicate_label_case_insensitively(app):
    with pytest.raises(ValidationError, match="already a sort of sport"):
        services.create_category(" judo ")
    assert Category.query.count() == len(DEFAULT_CATEGORIES)


def test_create_category_rejects_two_labels_that_reduce_to_one_value(app):
    services.create_category("Trail running")
    with pytest.raises(ValidationError, match="already a sort of sport"):
        services.create_category("trail-running")


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


@pytest.mark.parametrize("category", [v for v, _, _ in DEFAULT_CATEGORIES])
def test_create_workout_records_the_sort_of_sport(app, category):
    workout = services.create_workout("Leg day", ["Squat"], category)
    assert workout.category == category
    assert workout.category_label == services.category_map()[category].label


def test_create_workout_takes_a_sort_of_sport_added_on_the_page(app):
    services.create_category("Running")
    assert services.create_workout("Intervals", ["Sprint"], "running").category == (
        "running"
    )


def test_create_workout_defaults_to_the_default_sort_of_sport(app):
    """A caller that says nothing — or a POST without the field — still saves."""
    assert services.create_workout("Leg day", ["Squat"]).category == DEFAULT_CATEGORY


@pytest.mark.parametrize("category", ["running", "", "Judo", None])
def test_create_workout_rejects_an_unknown_sort_of_sport(app, category):
    with pytest.raises(ValidationError, match="Sort of sport must be one of"):
        services.create_workout("Leg day", ["Squat"], category)
    assert Workout.query.count() == 0


def test_create_workout_names_the_choices_it_knows_in_the_error(app):
    services.create_category("Running")
    with pytest.raises(ValidationError, match="Weights, Judo, Mobility, Others, Running"):
        services.create_workout("Leg day", ["Squat"], "chess")


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


@pytest.mark.parametrize("category", [v for v, _, _ in DEFAULT_CATEGORIES])
def test_log_session_takes_the_sort_of_sport_off_the_workout(app, category, user):
    workout = services.create_workout("Leg day", ["Squat", "Lunge"], category)
    session = services.log_session(
        workout.id,
        user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20), "good"
    )
    assert session.category == category
    assert session.category_label == services.category_map()[category].label


def test_log_session_keeps_the_sort_of_sport_the_workout_had(app, workout, user):
    """A workout re-labelled later must not recolour what is already logged."""
    session = services.log_session(
        workout.id,
        user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20), "good"
    )
    workout.category = "judo"
    db.session.commit()
    assert session.category == DEFAULT_CATEGORY


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


def test_log_session_defaults_a_missing_weight_to_no_extra_weight(app, workout, user):
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
        "Lunge": services.NO_WEIGHT,
    }
    assert services.DEFAULT_WEIGHT is services.NO_WEIGHT


def test_log_session_without_any_weights_records_no_extra_weight(app, workout, user):
    session = services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20), "good"
    )
    assert [log.weight for log in session.logs] == [None, None]
    assert [log.has_weight for log in session.logs] == [False, False]


def test_log_session_records_an_explicit_no_extra_weight(app, workout, user):
    """Picking "none" on the track page is not the same as a weight of 0."""
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        weights_by_exercise=weights_for(workout, 60, services.NO_WEIGHT),
    )
    lunge = next(log for log in session.logs if log.name == "Lunge")
    assert lunge.weight is None
    assert lunge.has_weight is False
    assert lunge.repetitions == 20  # still counted, in repetitions alone


def test_log_session_records_an_extra_exercise_without_extra_weight(
    app, workout, user
):
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        extra_exercises=[("Pull-up", 12, services.NO_WEIGHT)],
    )
    pull_up = next(log for log in session.logs if log.name == "Pull-up")
    assert pull_up.weight is None
    assert pull_up.weight_moved is None


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
    assert pull_up.weight is services.NO_WEIGHT


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


def test_weight_moved_is_none_without_an_extra_weight(app, workout, user):
    """No load carried, so there is no weight to report — not a weight of 0."""
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        weights_by_exercise=weights_for(workout, 60, services.NO_WEIGHT),
    )
    assert {log.name: log.weight_moved for log in session.logs} == {
        "Squat": 1800,
        "Lunge": None,
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


def test_session_total_weight_skips_exercises_without_extra_weight(app, workout, user):
    """A bodyweight set adds nothing; its repetitions are counted all the same."""
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        weights_by_exercise=weights_for(workout, 60, services.NO_WEIGHT),
    )
    assert session.total_weight == 1800
    assert session.total_repetitions == 50


def test_session_total_weight_is_zero_without_any_extra_weight(app, workout, user):
    session = services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20), "good"
    )
    assert session.total_weight == 0


# --------------------------------------------------------- log_session: sets


def sets_for(workout, *values):
    """Build an exercise id -> number of sets mapping in exercise order."""
    return {m.id: v for m, v in zip(workout.exercises, values)}


def test_log_session_multiplies_the_sets_by_the_repetitions_per_set(app, workout, user):
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 10, 12),  # per set, because sets are given
        "good",
        sets_by_exercise=sets_for(workout, 4, 3),
    )
    assert {log.name: log.repetitions for log in session.logs} == {
        "Squat": 40,  # 4 x 10
        "Lunge": 36,  # 3 x 12
    }
    assert session.total_repetitions == 76


def test_log_session_records_the_sets_it_counted_in(app, workout, user):
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 10, 12),
        "good",
        sets_by_exercise=sets_for(workout, 4, 3),
    )
    squat = next(log for log in session.logs if log.name == "Squat")
    assert squat.sets == 4
    assert squat.tracked_in_sets is True
    assert squat.repetitions_per_set == 10


def test_log_session_without_sets_takes_the_repetitions_as_the_total(app, workout, user):
    session = services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20), "good"
    )
    assert [log.repetitions for log in session.logs] == [30, 20]
    assert [log.sets for log in session.logs] == [None, None]
    assert [log.tracked_in_sets for log in session.logs] == [False, False]
    assert [log.repetitions_per_set for log in session.logs] == [None, None]
    assert services.DEFAULT_SETS is services.NO_SETS


def test_log_session_defaults_a_missing_sets_entry_to_no_sets(app, workout, user):
    """The sets are optional per exercise, the way the weight is."""
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 10, 20),
        "good",
        sets_by_exercise={workout.exercises[0].id: 4},
    )
    assert {log.name: log.repetitions for log in session.logs} == {
        "Squat": 40,  # 4 x 10
        "Lunge": 20,  # a total, as given
    }


def test_log_session_counts_sets_of_zero_repetitions_as_nothing_done(app, workout, user):
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 10, 0),
        "good",
        sets_by_exercise=sets_for(workout, 4, 3),
    )
    lunge = next(log for log in session.logs if log.name == "Lunge")
    assert lunge.repetitions == 0
    assert lunge.repetitions_per_set == 0


@pytest.mark.parametrize("sets", [0, -1, 21, 100])
def test_log_session_invalid_sets(app, workout, user, sets):
    with pytest.raises(ValidationError, match="between 1 and 20"):
        services.log_session(
            workout.id,
            user.id,
            date.today(),
            45,
            reps_for(workout, 10, 12),
            "good",
            sets_by_exercise=sets_for(workout, 4, sets),
        )
    assert WorkoutSession.query.count() == 0


def test_log_session_invalid_sets_names_the_exercise(app, workout, user):
    with pytest.raises(ValidationError, match="Sets for 'Lunge'"):
        services.log_session(
            workout.id,
            user.id,
            date.today(),
            45,
            reps_for(workout, 10, 12),
            "good",
            sets_by_exercise=sets_for(workout, 4, 0),
        )


def test_log_session_checks_the_repetitions_of_one_set_not_the_total(app, workout, user):
    """20 sets of 120 is far past the dropdown's top figure, and still valid."""
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 120, 120),
        "good",
        sets_by_exercise=sets_for(workout, 20, 20),
    )
    assert session.total_repetitions == 4800


def test_log_session_records_the_sets_of_an_extra_exercise(app, workout, user):
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        extra_exercises=[("Pull-up", 8, services.NO_WEIGHT, 3)],
    )
    pull_up = next(log for log in session.logs if log.name == "Pull-up")
    assert pull_up.repetitions == 24  # 3 x 8
    assert pull_up.sets == 3


def test_log_session_extra_exercise_without_sets_keeps_its_repetitions(app, workout, user):
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 30, 20),
        "good",
        extra_exercises=[("Pull-up", 8, 5)],
    )
    pull_up = next(log for log in session.logs if log.name == "Pull-up")
    assert pull_up.repetitions == 8
    assert pull_up.sets is None


def test_log_session_invalid_sets_on_an_extra_exercise(app, workout, user):
    with pytest.raises(ValidationError, match="Sets for 'Pull-up'"):
        services.log_session(
            workout.id,
            user.id,
            date.today(),
            45,
            reps_for(workout, 30, 20),
            "good",
            extra_exercises=[("Pull-up", 8, services.NO_WEIGHT, 21)],
        )
    assert WorkoutSession.query.count() == 0


def test_weight_moved_counts_every_repetition_of_every_set(app, workout, user):
    """The sets are already multiplied in, so the weight follows the total."""
    session = services.log_session(
        workout.id,
        user.id,
        date(2026, 9, 1),
        45,
        reps_for(workout, 10, 12),
        "good",
        weights_by_exercise=weights_for(workout, 60, services.NO_WEIGHT),
        sets_by_exercise=sets_for(workout, 4, 3),
    )
    assert {log.name: log.weight_moved for log in session.logs} == {
        "Squat": 2400,  # 4 sets x 10 repetitions x 60 kg
        "Lunge": None,
    }
    assert session.total_weight == 2400


# ------------------------------------------------- update_session, session_form


def test_get_session_by_id_or_none(app, workout, user):
    session = services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20), "good"
    )
    assert services.get_session(session.id) is session
    assert services.get_session(session.id + 1) is None
    assert services.get_session(None) is None


def test_update_session_rewrites_every_field(app, workout, user, other_user):
    session = services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20), "good",
        comment="Wrong on every count.",
    )
    services.update_session(
        session.id,
        workout.id, other_user.id, date(2026, 9, 3), 60,
        reps_for(workout, 10, 12), "bad", comment="Corrected.",
    )
    assert WorkoutSession.query.count() == 1  # the same session, written again
    again = services.get_session(session.id)
    assert (again.user_id, again.date, again.duration_minutes) == (
        other_user.id,
        date(2026, 9, 3),
        60,
    )
    assert (again.feeling, again.comment) == ("bad", "Corrected.")
    assert again.total_repetitions == 22


def test_update_session_replaces_the_exercise_logs(app, workout, user):
    session = services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20), "good",
        extra_exercises=[("Pull-up", 12)],
    )
    services.update_session(
        session.id,
        workout.id, user.id, date(2026, 9, 1), 45, reps_for(workout, 5, 5), "good",
        extra_exercises=[("Dip", 8)],
    )
    # the old logs are gone rather than piling up alongside the new ones
    assert SessionExercise.query.count() == 3
    assert {log.name for log in session.logs} == {"Squat", "Lunge", "Dip"}


def test_update_session_can_change_the_workout(app, user):
    """The point of the page: the wrong workout was picked to begin with."""
    legs = services.create_workout("Leg day", ["Squat"])
    randori = services.create_workout("Randori", ["Uchi-komi"], "judo")
    session = services.log_session(
        legs.id, user.id, date(2026, 9, 1), 45, {legs.exercises[0].id: 30}, "good"
    )
    services.update_session(
        session.id,
        randori.id, user.id, date(2026, 9, 1), 45,
        {randori.exercises[0].id: 40}, "good",
    )
    assert session.workout.name == "Randori"
    assert [(log.name, log.repetitions) for log in session.logs] == [("Uchi-komi", 40)]
    # and with the workout, the sort of sport the day is coloured by
    assert session.category == "judo"


def test_update_session_keeps_the_weights_and_sets_it_is_given(app, workout, user):
    squat, lunge = workout.exercises
    session = services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45, {squat.id: 10, lunge.id: 10}, "good"
    )
    services.update_session(
        session.id,
        workout.id, user.id, date(2026, 9, 1), 45, {squat.id: 10, lunge.id: 10}, "good",
        weights_by_exercise={squat.id: 60, lunge.id: services.NO_WEIGHT},
        sets_by_exercise={squat.id: 4, lunge.id: services.NO_SETS},
    )
    logs = {log.name: log for log in session.logs}
    assert (logs["Squat"].repetitions, logs["Squat"].sets) == (40, 4)
    assert logs["Squat"].weight == 60
    assert logs["Lunge"].weight is None


def test_update_session_rejects_an_unknown_session(app, workout, user):
    with pytest.raises(ValidationError, match="no longer exists"):
        services.update_session(
            404, workout.id, user.id, date(2026, 9, 1), 45,
            reps_for(workout, 30, 20), "good",
        )


def test_update_session_leaves_the_session_alone_when_it_is_invalid(
    app, workout, user
):
    """A rejected correction must not half-apply to what is already logged."""
    session = services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45, reps_for(workout, 30, 20), "good"
    )
    with pytest.raises(ValidationError):
        services.update_session(
            session.id,
            workout.id, user.id, date(2026, 9, 3), 60,
            reps_for(workout, 5, 5), "splendid",  # not a feeling
        )
    again = services.get_session(session.id)
    assert (again.date, again.duration_minutes, again.feeling) == (
        date(2026, 9, 1),
        45,
        "good",
    )
    assert again.total_repetitions == 50


def test_session_form_reads_a_session_back_as_the_form_filled_it(app, workout, user):
    squat, lunge = workout.exercises
    session = services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45, {squat.id: 30, lunge.id: 20}, "okay",
        weights_by_exercise={squat.id: 40, lunge.id: services.NO_WEIGHT},
        extra_exercises=[("Pull-up", 12, 5)],
        comment="Knee fine.",
    )
    form = services.session_form(session)
    assert form["id"] == session.id
    assert (form["workout_id"], form["user_id"]) == (workout.id, user.id)
    assert (form["date"], form["duration_minutes"]) == (date(2026, 9, 1), 45)
    assert (form["feeling"], form["comment"]) == ("okay", "Knee fine.")
    assert form["tracking_mode"] == services.TOTAL_MODE
    assert form["repetitions"] == {squat.id: 30, lunge.id: 20}
    assert form["weights"] == {squat.id: 40, lunge.id: None}
    assert form["sets"] == {squat.id: None, lunge.id: None}
    assert form["extras"] == [
        {"name": "Pull-up", "repetitions": 12, "weight": 5, "sets": None}
    ]


def test_session_form_reads_sets_back_per_set(app, workout, user):
    """The dropdown means repetitions per set, so that is what comes back."""
    squat, lunge = workout.exercises
    session = services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45, {squat.id: 10, lunge.id: 12}, "good",
        sets_by_exercise={squat.id: 4, lunge.id: 3},
        extra_exercises=[("Pull-up", 6, services.NO_WEIGHT, 2)],
    )
    form = services.session_form(session)
    assert form["tracking_mode"] == services.SETS_MODE
    assert form["repetitions"] == {squat.id: 10, lunge.id: 12}
    assert form["sets"] == {squat.id: 4, lunge.id: 3}
    assert form["extras"][0]["repetitions"] == 6
    assert form["extras"][0]["sets"] == 2


def test_session_form_reads_a_total_inside_a_sets_session_as_one_set(
    app, workout, user
):
    squat, lunge = workout.exercises
    session = services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45, {squat.id: 10, lunge.id: 25}, "good",
        sets_by_exercise={squat.id: 4},  # the lunges were counted as a total
    )
    form = services.session_form(session)
    assert form["tracking_mode"] == services.SETS_MODE
    # one set of 25 is the 25 that is stored, so re-saving changes nothing
    assert (form["repetitions"][lunge.id], form["sets"][lunge.id]) == (25, 1)


def test_session_form_survives_a_round_trip(app, workout, user):
    """Re-saving an untouched form logs exactly what is already there."""
    squat, lunge = workout.exercises
    session = services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45, {squat.id: 10, lunge.id: 12}, "good",
        weights_by_exercise={squat.id: 60, lunge.id: services.NO_WEIGHT},
        sets_by_exercise={squat.id: 4, lunge.id: 3},
        extra_exercises=[("Pull-up", 6, 5, 2)],
    )
    before = services.session_form(session)
    services.update_session(
        session.id,
        before["workout_id"], before["user_id"], before["date"],
        before["duration_minutes"], before["repetitions"], before["feeling"],
        extra_exercises=[
            (e["name"], e["repetitions"], e["weight"], e["sets"])
            for e in before["extras"]
        ],
        comment=before["comment"],
        weights_by_exercise=before["weights"],
        sets_by_exercise=before["sets"],
    )
    assert services.session_form(session) == before


def test_date_choices_span_and_order():
    today = date(2026, 9, 8)
    choices = services.date_choices(days_back=30, today=today)
    assert len(choices) == 31
    assert choices[0] == today
    assert choices[-1] == today - timedelta(days=30)


def test_date_choices_add_a_date_the_window_misses():
    """A session being corrected has to be offered its own date."""
    today = date(2026, 9, 8)
    old_day = date(2026, 1, 1)
    choices = services.date_choices(days_back=30, today=today, include=old_day)
    assert choices[-1] == old_day  # oldest, so last: the list stays sorted
    assert len(choices) == 32


def test_date_choices_do_not_repeat_a_date_already_in_the_window():
    today = date(2026, 9, 8)
    choices = services.date_choices(days_back=30, today=today, include=today)
    assert len(choices) == 31


def test_duration_and_repetition_choices_bounds():
    assert services.DURATION_CHOICES[0] == 10
    assert services.DURATION_CHOICES[-1] == 90
    assert services.REPETITION_CHOICES[0] == 0
    assert services.REPETITION_CHOICES[-1] == 120
    assert len(services.REPETITION_CHOICES) == 121


def test_set_choices_bounds_and_default():
    assert services.SET_CHOICES[0] == 1
    assert services.SET_CHOICES[-1] == 20
    assert len(services.SET_CHOICES) == 20
    assert services.NO_SETS is None
    assert services.NO_SETS not in services.SET_CHOICES
    assert services.DEFAULT_SETS is services.NO_SETS


def test_tracking_modes_offer_a_total_and_sets(app):
    assert services.DEFAULT_TRACKING_MODE == services.TOTAL_MODE
    assert set(services.TRACKING_MODES) == {services.TOTAL_MODE, services.SETS_MODE}
    assert all(label for label in services.TRACKING_MODES.values())


def test_weight_choices_bounds_and_default():
    assert services.WEIGHT_CHOICES[0] == 1
    assert services.WEIGHT_CHOICES[-1] == 200
    assert len(services.WEIGHT_CHOICES) == 200
    assert services.NO_WEIGHT is None
    assert services.NO_WEIGHT not in services.WEIGHT_CHOICES
    assert services.DEFAULT_WEIGHT is services.NO_WEIGHT
