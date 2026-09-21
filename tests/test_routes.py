import re
from datetime import date, timedelta

from src import routes, services
from src.models import (
    DEFAULT_CATEGORIES,
    DEFAULT_CATEGORY,
    Category,
    SessionExercise,
    User,
    Workout,
    WorkoutSession,
)


def test_index_redirects_to_create(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/create" in response.headers["Location"]


# ----------------------------------------------------------------- users page


def test_users_page_renders(client):
    response = client.get("/users")
    assert response.status_code == 200
    assert b"No users yet" in response.data


def test_nav_links_to_the_users_page(client):
    assert b'href="/users"' in client.get("/create").data


def test_create_user_via_form(client, app):
    response = client.post(
        "/users", data={"name": "Alex", "age": "34"}, follow_redirects=True
    )
    assert b"User &#39;Alex&#39; saved." in response.data
    with app.app_context():
        user = User.query.one()
        assert (user.name, user.age) == ("Alex", 34)


def test_users_page_lists_users_with_their_age(client, app):
    with app.app_context():
        services.create_user("Alex", 34)
    html = client.get("/users").data.decode()
    assert "Alex" in html
    assert "34 years old" in html


def test_create_user_form_shows_validation_error(client, app):
    response = client.post("/users", data={"name": "", "age": "34"})
    assert b"User name is required." in response.data
    with app.app_context():
        assert User.query.count() == 0


def test_create_user_form_rejects_a_non_numeric_age(client, app):
    """type=number keeps this out of the browser; by hand it must not blow up."""
    response = client.post("/users", data={"name": "Alex", "age": "old"})
    assert response.status_code == 200
    assert b"Age must be between 1 and 120." in response.data
    with app.app_context():
        assert User.query.count() == 0


def test_user_age_input_carries_the_service_bounds(client):
    html = client.get("/users").data.decode()
    assert f'min="{services.MIN_AGE}"' in html
    assert f'max="{services.MAX_AGE}"' in html


# --------------------------------------------------------------- create page


def test_create_page_renders(client):
    response = client.get("/create")
    assert response.status_code == 200
    assert b"Create a workout" in response.data


def test_create_workout_via_form(client, app):
    response = client.post(
        "/create",
        data={"name": "Leg day", "exercises": ["Squat", "Lunge", ""]},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"saved" in response.data
    with app.app_context():
        workout = Workout.query.one()
        assert workout.name == "Leg day"
        assert len(workout.exercises) == 2


def test_create_page_offers_known_exercises(client, app, user):
    with app.app_context():
        services.create_workout("Leg day", ["Squat", "Lunge"])
        workout = services.create_workout("Push day", ["Bench press", "Squat"])
        services.log_session(
            workout.id,
            user.id,
            date(2026, 9, 1),
            45,
            {m.id: 10 for m in workout.exercises},
            "good",
            extra_exercises=[("Pull-up", 12)],
        )
    html = client.get("/create").data.decode()
    assert "Or select an exercise you've already used" in html
    for name in ("Squat", "Lunge", "Bench press", "Pull-up"):
        assert f'data-exercise="{name}"' in html
    assert html.count('data-exercise="Squat"') == 1  # listed once, not per workout


def test_create_page_has_no_picker_when_no_exercises_exist(client):
    html = client.get("/create").data.decode()
    assert 'data-exercise="' not in html  # the chips; the click handler stays
    assert "Or select an exercise" not in html


def test_create_workout_from_picked_exercises(client, app):
    """The picker just fills in exercises fields, so the POST looks the same."""
    with app.app_context():
        services.create_workout("Leg day", ["Squat"])
    client.post(
        "/create",
        data={"name": "Leg day 2", "exercises": ["Squat", "Squat", "Lunge"]},
        follow_redirects=True,
    )
    with app.app_context():
        workout = Workout.query.filter_by(name="Leg day 2").one()
        assert [m.name for m in workout.exercises] == ["Squat", "Lunge"]


def test_create_workout_form_shows_validation_error(client):
    response = client.post("/create", data={"name": "", "exercises": ["Squat"]})
    assert b"Workout name is required." in response.data


def test_create_page_offers_every_sort_of_sport(client):
    html = client.get("/create").data.decode()
    assert f'name="{routes.CATEGORY_FIELD}"' in html
    for value, label, color in DEFAULT_CATEGORIES:
        assert f'value="{value}"' in html
        assert f">{label}</option>" in html
        assert f"--heat: {color}" in html  # the legend under the add form
    # the sort of sport belongs to the workout, so it is asked before its
    # exercises
    assert html.index(f'name="{routes.CATEGORY_FIELD}"') < html.index(
        'name="exercises"'
    )


def test_create_workout_records_the_chosen_sort_of_sport(client, app):
    response = client.post(
        "/create",
        data={
            "name": "Randori",
            "exercises": ["Uchi-komi"],
            routes.CATEGORY_FIELD: "judo",
        },
        follow_redirects=True,
    )
    assert b"(judo)" in response.data  # the flash names it
    with app.app_context():
        assert Workout.query.one().category == "judo"


def test_create_workout_defaults_the_sort_of_sport_when_the_field_is_missing(
    client, app
):
    """A hand-crafted POST without the field still saves the workout."""
    client.post(
        "/create",
        data={"name": "Leg day", "exercises": ["Squat"]},
        follow_redirects=True,
    )
    with app.app_context():
        assert Workout.query.one().category == DEFAULT_CATEGORY


def test_create_workout_rejects_an_unknown_sort_of_sport(client, app):
    response = client.post(
        "/create",
        data={
            "name": "Leg day",
            "exercises": ["Squat"],
            routes.CATEGORY_FIELD: "chess",
        },
    )
    assert b"Sort of sport must be one of" in response.data
    with app.app_context():
        assert Workout.query.count() == 0


def test_create_page_lists_a_workout_with_its_sort_of_sport(client, app):
    with app.app_context():
        services.create_workout("Randori", ["Uchi-komi"], "judo")
    html = client.get("/create").data.decode()
    listing = html[html.index("Your workouts") :]
    assert "Judo" in listing


def test_add_a_sort_of_sport_from_the_create_page(client, app):
    response = client.post(
        "/categories",
        data={routes.CATEGORY_LABEL_FIELD: "Running"},
        follow_redirects=True,
    )
    assert b"Sort of sport &#39;Running&#39; added." in response.data
    html = response.data.decode()
    assert 'value="running"' in html and ">Running</option>" in html
    with app.app_context():
        assert Category.query.filter_by(value="running").one().label == "Running"


def test_added_sort_of_sport_can_be_given_to_a_workout(client, app):
    client.post("/categories", data={routes.CATEGORY_LABEL_FIELD: "Running"})
    client.post(
        "/create",
        data={
            "name": "Intervals",
            "exercises": ["Sprint"],
            routes.CATEGORY_FIELD: "running",
        },
    )
    with app.app_context():
        assert Workout.query.one().category == "running"


def test_add_a_sort_of_sport_shows_a_validation_error(client, app):
    response = client.post(
        "/categories",
        data={routes.CATEGORY_LABEL_FIELD: " judo "},
        follow_redirects=True,
    )
    assert b"already a sort of sport" in response.data
    with app.app_context():
        assert Category.query.count() == len(DEFAULT_CATEGORIES)


# ---------------------------------------------------------------- track page


def flat(html: str) -> str:
    """Collapse whitespace, so an assertion can ignore the template's wrapping."""
    return " ".join(html.split())


def track_form(workout, user, reps, weights=None, sets=None, **overrides):
    """POST data for /track: a reps- and a weight- field per exercise.

    `weights` defaults to the "no extra weight" option for every exercise, the
    way the form's own dropdowns are pre-selected.

    `sets` adds a sets- field per exercise and switches the mode dropdown over
    to counting in sets, which makes `reps` the repetitions of one set. Left
    out, the form counts totals, the way it opens.

    The sort of sport is not among the fields: it belongs to the workout.
    """
    data = {
        "workout_id": workout.id,
        "user_id": user.id,
        "date": "2026-09-01",
        "duration": "45",
        "feeling": "good",
        routes.MODE_FIELD: services.TOTAL_MODE,
    }
    weights = weights if weights is not None else [routes.NO_WEIGHT_VALUE] * len(reps)
    data.update({f"reps-{m.id}": str(v) for m, v in zip(workout.exercises, reps)})
    data.update({f"weight-{m.id}": str(v) for m, v in zip(workout.exercises, weights)})
    if sets is not None:
        data[routes.MODE_FIELD] = services.SETS_MODE
        data.update({f"sets-{m.id}": str(v) for m, v in zip(workout.exercises, sets)})
    data.update(overrides)
    return data


def test_track_page_does_not_ask_for_the_sort_of_sport(client, app, user):
    """It is the workout's, picked on the create page, so the form names it."""
    with app.app_context():
        services.create_workout("Randori", ["Uchi-komi"], "judo")
    html = client.get("/track").data.decode()
    assert f'name="{routes.CATEGORY_FIELD}"' not in html
    assert "Randori · Judo" in html


def test_track_logs_the_workouts_sort_of_sport(client, app, user):
    with app.app_context():
        workout = services.create_workout("Randori", ["Uchi-komi"], "judo")
        form = track_form(workout, user, [30])
    response = client.post("/track", data=form, follow_redirects=True)
    assert b"(judo, " in response.data  # the summary names the sort of sport
    with app.app_context():
        assert WorkoutSession.query.one().category == "judo"


def test_track_page_contains_all_dropdowns(client, app, user):
    with app.app_context():
        services.create_workout("Leg day", ["Squat"])
    response = client.get("/track")
    html = response.data.decode()
    assert "Leg day" in html
    assert 'value="10"' in html and 'value="90"' in html  # duration bounds
    assert 'value="0"' in html and 'value="120"' in html  # repetition bounds
    assert 'name="date"' in html
    for feeling in ("good", "okay", "bad"):
        assert feeling in html


def test_track_page_lists_every_exercise_of_every_workout(client, app, user):
    with app.app_context():
        legs = services.create_workout("Leg day", ["Squat", "Lunge"])
        push = services.create_workout("Push day", ["Bench press"])
        ids = [m.id for m in legs.exercises + push.exercises]
        names = [m.name for m in legs.exercises + push.exercises]
    html = client.get("/track").data.decode()
    for name in names:
        assert name in html
    for exercise_id in ids:
        assert f'name="reps-{exercise_id}"' in html


def test_track_session_via_form(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat", "Lunge"])
        data = track_form(workout, user, (30, 20))
    response = client.post("/track", data=data, follow_redirects=True)
    assert b"Logged Leg day" in response.data
    assert b"50 repetitions" in response.data
    with app.app_context():
        session = WorkoutSession.query.one()
        assert session.date == date(2026, 9, 1)
        assert session.duration_minutes == 45
        assert {log.exercise.name: log.repetitions for log in session.logs} == {
            "Squat": 30,
            "Lunge": 20,
        }


def test_track_session_ignores_other_workouts_exercise_fields(client, app, user):
    """Without JS the form submits every workout's fields; only one counts."""
    with app.app_context():
        legs = services.create_workout("Leg day", ["Squat"])
        push = services.create_workout("Push day", ["Bench press"])
        data = track_form(legs, user, (30,))
        data[f"reps-{push.exercises[0].id}"] = "99"
    client.post("/track", data=data, follow_redirects=True)
    with app.app_context():
        log = SessionExercise.query.one()
        assert log.repetitions == 30
        assert log.exercise.name == "Squat"


def test_track_session_missing_exercise_shows_error(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat", "Lunge"])
        data = track_form(workout, user, (30, 20))
        del data[f"reps-{workout.exercises[1].id}"]
    response = client.post("/track", data=data)
    assert b"Enter repetitions for &#39;Lunge&#39;." in response.data
    with app.app_context():
        assert WorkoutSession.query.count() == 0


def test_track_session_invalid_input_shows_error(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, user, (30,), feeling="amazing")
    response = client.post("/track", data=data)
    assert b"Feeling must be good, okay or bad." in response.data
    with app.app_context():
        assert WorkoutSession.query.count() == 0


def test_track_session_out_of_range_repetitions_shows_error(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, user, (500,))
    response = client.post("/track", data=data)
    assert b"must be between 0 and 120" in response.data
    with app.app_context():
        assert WorkoutSession.query.count() == 0


def test_track_page_offers_an_extra_exercise_row(client, app, user):
    with app.app_context():
        services.create_workout("Leg day", ["Squat"])
    html = client.get("/track").data.decode()
    assert 'name="extra-name"' in html
    assert 'name="extra-reps"' in html
    assert "addExtraExercise()" in html
    assert 'id="extra-row-template"' in html  # cloned by the button


def test_track_session_with_extra_exercise_via_form(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, user, (30,))
        data["extra-name"] = "Pull-up"
        data["extra-reps"] = "12"
    response = client.post("/track", data=data, follow_redirects=True)
    assert b"42 repetitions" in response.data  # 30 + 12
    with app.app_context():
        session = WorkoutSession.query.one()
        assert {log.name: log.repetitions for log in session.logs} == {
            "Squat": 30,
            "Pull-up": 12,
        }
        assert Workout.query.one().exercises[0].name == "Squat"  # workout untouched


def test_track_session_ignores_blank_extra_exercise_row(client, app, user):
    """The form always renders one empty row; leaving it alone logs nothing."""
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, user, (30,))
        data["extra-name"] = ""
        data["extra-reps"] = "10"
    client.post("/track", data=data, follow_redirects=True)
    with app.app_context():
        assert SessionExercise.query.count() == 1  # just the Squat


def test_track_session_with_several_extra_exercises_via_form(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, user, (30,))
    data = {**data, "extra-name": ["Pull-up", "", "Dip"], "extra-reps": ["12", "10", "8"]}
    client.post("/track", data=data, follow_redirects=True)
    with app.app_context():
        session = WorkoutSession.query.one()
        assert {log.name: log.repetitions for log in session.logs} == {
            "Squat": 30,
            "Pull-up": 12,
            "Dip": 8,
        }


def test_track_page_offers_the_two_ways_of_counting(client, app, user):
    with app.app_context():
        services.create_workout("Leg day", ["Squat"])
    html = client.get("/track").data.decode()
    assert f'name="{routes.MODE_FIELD}"' in html
    for value, label in services.TRACKING_MODES.items():
        assert f'value="{value}"' in html
        assert label in html
    assert 'name="sets-' in html
    assert f'name="{routes.EXTRA_SETS_FIELD}"' in html
    assert 'value="20"' in html  # the top of the sets dropdown


def test_track_session_in_sets_logs_sets_times_repetitions(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat", "Lunge"])
        data = track_form(workout, user, (10, 12), sets=(4, 3))
    response = client.post("/track", data=data, follow_redirects=True)
    assert b"76 repetitions" in response.data  # 4 x 10 + 3 x 12
    with app.app_context():
        session = WorkoutSession.query.one()
        assert {log.name: (log.repetitions, log.sets) for log in session.logs} == {
            "Squat": (40, 4),
            "Lunge": (36, 3),
        }


def test_track_session_counting_a_total_ignores_the_sets_fields(client, app, user):
    """Without JS the disabled sets column is submitted anyway; it must not count."""
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, user, (30,))
        data[f"sets-{workout.exercises[0].id}"] = "4"
    response = client.post("/track", data=data, follow_redirects=True)
    assert b"30 repetitions" in response.data
    with app.app_context():
        log = SessionExercise.query.one()
        assert (log.repetitions, log.sets) == (30, None)


def test_track_session_with_an_unknown_mode_counts_a_total(client, app, user):
    """Only a hand-crafted POST can say anything else; it falls back, not fails."""
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, user, (30,), sets=(4,))
        data[routes.MODE_FIELD] = "pyramid"
    client.post("/track", data=data, follow_redirects=True)
    with app.app_context():
        assert SessionExercise.query.one().repetitions == 30


def test_track_session_in_sets_with_an_extra_exercise(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, user, (10,), sets=(4,))
        data[routes.EXTRA_NAME_FIELD] = "Pull-up"
        data[routes.EXTRA_REPS_FIELD] = "8"
        data[routes.EXTRA_SETS_FIELD] = "3"
    response = client.post("/track", data=data, follow_redirects=True)
    assert b"64 repetitions" in response.data  # 4 x 10 + 3 x 8
    with app.app_context():
        session = WorkoutSession.query.one()
        assert {log.name: (log.repetitions, log.sets) for log in session.logs} == {
            "Squat": (40, 4),
            "Pull-up": (24, 3),
        }


def test_track_session_with_an_impossible_sets_count_shows_error(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, user, (10,), sets=(0,))
    response = client.post("/track", data=data)
    assert b"Sets for &#39;Squat&#39; must be between 1 and 20." in response.data
    with app.app_context():
        assert WorkoutSession.query.count() == 0


def test_track_session_extra_already_in_workout_shows_error(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, user, (30,))
        data["extra-name"] = "squat"
        data["extra-reps"] = "12"
    response = client.post("/track", data=data)
    assert b"already an exercise of Leg day" in response.data
    with app.app_context():
        assert WorkoutSession.query.count() == 0


def test_track_page_offers_a_weight_dropdown_per_exercise(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat", "Lunge"])
        ids = [m.id for m in workout.exercises]
    html = client.get("/track").data.decode()
    for exercise_id in ids:
        assert f'name="weight-{exercise_id}"' in html
    assert 'name="extra-weight"' in html
    # the ends of WEIGHT_CHOICES, behind "no extra weight" as the pre-selected one
    assert f'value="{services.WEIGHT_CHOICES[0]}"' in html
    assert f'value="{services.WEIGHT_CHOICES[-1]}"' in html
    assert f'value="{routes.NO_WEIGHT_VALUE}" selected' in html
    assert f"extra {services.WEIGHT_UNIT}" in html


def test_track_session_records_the_weight_via_form(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat", "Lunge"])
        data = track_form(workout, user, (30, 20), weights=(60, 25))
    response = client.post("/track", data=data, follow_redirects=True)
    assert b"50 repetitions" in response.data
    assert f"2300 {services.WEIGHT_UNIT}".encode() in response.data  # 1800 + 500
    with app.app_context():
        session = WorkoutSession.query.one()
        assert {log.name: log.weight for log in session.logs} == {
            "Squat": 60,
            "Lunge": 25,
        }


def test_track_session_without_weight_fields_uses_the_default(client, app, user):
    """A hand-crafted POST that skips them still logs, with no extra weight."""
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, user, (30,))
        del data[f"weight-{workout.exercises[0].id}"]
    client.post("/track", data=data, follow_redirects=True)
    with app.app_context():
        assert SessionExercise.query.one().weight is services.DEFAULT_WEIGHT


def test_track_session_records_no_extra_weight_via_form(client, app, user):
    """The dropdown's "none" option, which is what it opens on."""
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, user, (30,))
    response = client.post("/track", data=data, follow_redirects=True)
    # the flash reports repetitions alone; there is no weight to mention
    assert b"30 repetitions)" in response.data
    with app.app_context():
        assert SessionExercise.query.one().weight is None


def test_track_session_extra_exercise_without_extra_weight_via_form(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, user, (30,))
        data["extra-name"] = "Pull-up"
        data["extra-reps"] = "12"
        data["extra-weight"] = routes.NO_WEIGHT_VALUE
    client.post("/track", data=data, follow_redirects=True)
    with app.app_context():
        pull_up = SessionExercise.query.filter_by(extra_name="Pull-up").one()
        assert pull_up.weight is None


def test_track_session_out_of_range_weight_shows_error(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, user, (30,), weights=(500,))
    response = client.post("/track", data=data)
    assert b"must be between 1 and 200" in response.data
    with app.app_context():
        assert WorkoutSession.query.count() == 0


def test_track_session_extra_exercise_weight_via_form(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, user, (30,))
        data["extra-name"] = "Pull-up"
        data["extra-reps"] = "12"
        data["extra-weight"] = "15"
    client.post("/track", data=data, follow_redirects=True)
    with app.app_context():
        pull_up = SessionExercise.query.filter_by(extra_name="Pull-up").one()
        assert pull_up.weight == 15


def test_track_session_weights_several_extra_exercises_by_position(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, user, (30,))
    data = {
        **data,
        "extra-name": ["Pull-up", "", "Dip"],
        "extra-reps": ["12", "10", "8"],
        "extra-weight": ["15", "1", "20"],
    }
    client.post("/track", data=data, follow_redirects=True)
    with app.app_context():
        session = WorkoutSession.query.one()
        assert {log.name: log.weight for log in session.logs} == {
            "Squat": None,
            "Pull-up": 15,
            "Dip": 20,
        }


def test_track_page_offers_every_user(client, app):
    with app.app_context():
        services.create_workout("Leg day", ["Squat"])
        services.create_user("Alex", 34)
        services.create_user("Sam", 41)
    html = client.get("/track").data.decode()
    assert 'name="user_id"' in html
    assert ">Alex</option>" in html and ">Sam</option>" in html


def test_track_page_needs_a_user_before_a_form(client, app):
    with app.app_context():
        services.create_workout("Leg day", ["Squat"])
    html = client.get("/track").data.decode()
    assert "You need a user first" in html
    assert 'name="user_id"' not in html


def test_track_session_is_logged_against_the_user(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, user, (30,))
    response = client.post("/track", data=data, follow_redirects=True)
    assert b"Logged Leg day for Alex" in response.data
    with app.app_context():
        assert WorkoutSession.query.one().user.name == "Alex"


def test_track_session_unknown_user_shows_error(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, user, (30,), user_id="999")
    response = client.post("/track", data=data)
    assert b"Select a user that exists." in response.data
    with app.app_context():
        assert WorkoutSession.query.count() == 0


def test_track_page_offers_a_comment_field(client, app, user):
    with app.app_context():
        services.create_workout("Leg day", ["Squat"])
    html = client.get("/track").data.decode()
    assert 'name="comment"' in html
    assert f'maxlength="{services.MAX_COMMENT_LENGTH}"' in html


def test_track_session_with_a_comment_via_form(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, user, (30,), comment="  Felt strong.  ")
    client.post("/track", data=data, follow_redirects=True)
    with app.app_context():
        assert WorkoutSession.query.one().comment == "Felt strong."


def test_track_session_without_a_comment_via_form(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, user, (30,), comment="")
    client.post("/track", data=data, follow_redirects=True)
    with app.app_context():
        assert WorkoutSession.query.one().comment is None


def test_track_session_over_long_comment_shows_error(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(
            workout, user, (30,), comment="x" * (services.MAX_COMMENT_LENGTH + 1)
        )
    response = client.post("/track", data=data)
    assert b"Keep the comment under 2000 characters." in response.data
    with app.app_context():
        assert WorkoutSession.query.count() == 0


# ------------------------------------------- track page: correcting a session


def logged(user, **kwargs):
    """One logged session on 1 September, for the tests that correct it.

    Called inside an app context, like every other service call here, and
    gives back the session's id and its workout so a form can be built for it.
    """
    workout = services.create_workout("Leg day", ["Squat", "Lunge"])
    session = services.log_session(
        workout.id, user.id, date(2026, 9, 1), 45,
        {m.id: v for m, v in zip(workout.exercises, (30, 20))}, "good",
        **kwargs,
    )
    return session.id, workout


def test_day_panel_links_each_session_to_the_track_form(client, app, user):
    with app.app_context():
        session_id, _ = logged(user)
    html = client.get("/analytics?day=2026-09-01").data.decode()
    panel = html[html.index('class="day-detail"') : html.index("Workouts performed")]
    assert f'href="/track/{session_id}"' in panel
    assert "Correct this session" in panel


def test_track_form_opens_filled_in_with_the_session(client, app, user):
    with app.app_context():
        session_id, workout = logged(user, comment="Knee fine.")
        workout_id = workout.id
        squat_id, lunge_id = (m.id for m in workout.exercises)
    html = client.get(f"/track/{session_id}").data.decode()
    assert "Correct a session" in html
    assert "Save changes" in html
    assert f'<option value="{workout_id}" selected>' in flat(html)
    assert f'<option value="2026-09-01" selected>' in flat(html)
    assert "Knee fine.</textarea>" in html
    # the repetitions of this session's own exercises, not the defaults
    reps = html[html.index(f'name="{routes.REPS_FIELD_PREFIX}{squat_id}"') :]
    assert '<option value="30" selected>' in flat(reps[: reps.index("</select>")])
    reps = html[html.index(f'name="{routes.REPS_FIELD_PREFIX}{lunge_id}"') :]
    assert '<option value="20" selected>' in flat(reps[: reps.index("</select>")])


def test_track_form_offers_a_date_older_than_the_dropdown_reaches(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        old_day = date.today() - timedelta(days=400)
        session = services.log_session(
            workout.id, user.id, old_day, 45, {workout.exercises[0].id: 30}, "good"
        )
        session_id = session.id
    html = client.get(f"/track/{session_id}").data.decode()
    assert f'<option value="{old_day.isoformat()}" selected>' in flat(html)


def test_track_form_fills_in_the_extras_and_leaves_a_blank_row(client, app, user):
    with app.app_context():
        session_id, _ = logged(user, extra_exercises=[("Pull-up", 12)])
    html = client.get(f"/track/{session_id}").data.decode()
    assert 'value="Pull-up"' in html
    # one row for the extra, one empty row to add another, one in the template
    assert html.count(f'name="{routes.EXTRA_NAME_FIELD}"') == 3


def test_track_form_opens_in_the_mode_the_session_was_counted_in(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        squat = workout.exercises[0]
        session = services.log_session(
            workout.id, user.id, date(2026, 9, 1), 45, {squat.id: 10}, "good",
            sets_by_exercise={squat.id: 4},
        )
        session_id, squat_id = session.id, squat.id
    html = client.get(f"/track/{session_id}").data.decode()
    assert f'<option value="{services.SETS_MODE}" selected>' in flat(html)
    sets = html[html.index(f'name="{routes.SETS_FIELD_PREFIX}{squat_id}"') :]
    assert '<option value="4" selected>' in flat(sets[: sets.index("</select>")])


def test_track_correction_writes_the_session_again(client, app, user):
    with app.app_context():
        session_id, workout = logged(user)
        form = track_form(workout, user, [5, 5], feeling="bad", duration="60")
    response = client.post(f"/track/{session_id}", data=form, follow_redirects=True)
    assert b"Updated Leg day" in response.data
    with app.app_context():
        assert WorkoutSession.query.count() == 1  # corrected, not duplicated
        session = services.get_session(session_id)
        assert (session.feeling, session.duration_minutes) == ("bad", 60)
        assert session.total_repetitions == 10


def test_track_correction_returns_to_the_day_it_now_falls_on(client, app, user):
    with app.app_context():
        session_id, workout = logged(user)
        form = track_form(workout, user, [30, 20], date="2026-09-05")
    response = client.post(f"/track/{session_id}", data=form)
    assert response.status_code == 302
    assert response.headers["Location"] == "/analytics?day=2026-09-05#day"


def test_track_correction_can_change_the_workout(client, app, user):
    with app.app_context():
        session_id, _ = logged(user)
        randori = services.create_workout("Randori", ["Uchi-komi"], "judo")
        form = track_form(randori, user, [40])
    client.post(f"/track/{session_id}", data=form, follow_redirects=True)
    with app.app_context():
        session = services.get_session(session_id)
        assert session.workout.name == "Randori"
        assert session.category == "judo"  # and with it the day's colour


def test_track_correction_shows_a_validation_error(client, app, user):
    with app.app_context():
        session_id, workout = logged(user)
        form = track_form(workout, user, [5, 5], feeling="splendid")
    response = client.post(f"/track/{session_id}", data=form)
    assert b"Feeling must be good, okay or bad." in response.data
    with app.app_context():
        session = services.get_session(session_id)
        assert (session.feeling, session.total_repetitions) == ("good", 50)


def test_track_an_unknown_session_goes_back_to_the_analytics_page(client, app, user):
    response = client.get("/track/404", follow_redirects=True)
    assert b"That session no longer exists." in response.data
    assert b"Analytics" in response.data


def test_tracking_a_new_session_is_unchanged_by_the_correction_route(
    client, app, user
):
    """/track without an id still adds a session rather than editing one."""
    with app.app_context():
        _, workout = logged(user)
        form = track_form(workout, user, [10, 10])
    response = client.post("/track", data=form, follow_redirects=True)
    assert b"Logged Leg day" in response.data
    with app.app_context():
        assert WorkoutSession.query.count() == 2


# ------------------------------------------------------------ analytics page


def test_analytics_page_renders_with_data(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat", "Lunge"])
        reps = {m.id: v for m, v in zip(workout.exercises, (30, 20))}
        services.log_session(workout.id, user.id, date.today(), 45, reps, "good")
    html = client.get("/analytics").data.decode()
    assert "Activity, last 12 months" in html
    assert "heatmap" in html
    assert "Workouts performed" in html
    assert "Leg day" in html
    assert "Repetitions per exercise" in html
    assert "Squat" in html and "Lunge" in html
    assert "50 " in html  # total repetitions across both exercises
    assert "feeling-chart" in html
    assert "bar-good" in html


def test_analytics_page_lists_extra_exercises(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        services.log_session(
            workout.id,
            user.id,
            date.today(),
            45,
            {workout.exercises[0].id: 30},
            "good",
            extra_exercises=[("Pull-up", 12)],
        )
    html = client.get("/analytics").data.decode()
    assert "Pull-up" in html
    assert "extra, this session only" in html
    assert "42 " in html  # grand total includes the extra


def test_analytics_activity_map_colours_a_day_by_its_sort_of_sport(client, app, user):
    with app.app_context():
        workout = services.create_workout("Randori", ["Uchi-komi"], "judo")
        judo = services.category_map()["judo"].color
        services.log_session(
            workout.id, user.id, date.today(), 45,
            {workout.exercises[0].id: 30}, "good",
        )
    html = client.get("/analytics").data.decode()
    activity = html[: html.index("Workouts performed")]
    assert f'style="--heat: {judo}"' in activity
    assert f'title="{date.today().isoformat()}: 1 session · Judo"' in activity


def test_analytics_activity_map_has_a_legend_of_every_sort_of_sport(client, app):
    html = client.get("/analytics").data.decode()
    legend = html[html.index("category-legend") : html.index("Workouts performed")]
    for value, label, color in DEFAULT_CATEGORIES:
        assert f'style="--heat: {color}"' in legend
        assert label in legend


def test_analytics_legend_lists_a_sort_of_sport_added_on_the_create_page(client, app):
    with app.app_context():
        running = services.create_category("Running")
        color = running.color
    legend = client.get("/analytics").data.decode()
    legend = legend[legend.index("category-legend") : legend.index("Workouts performed")]
    assert "Running" in legend and f'style="--heat: {color}"' in legend


def test_analytics_exercise_heatmaps_are_not_coloured_by_sort_of_sport(
    client, app, user
):
    with app.app_context():
        workout = services.create_workout("Randori", ["Uchi-komi"], "judo")
        judo = services.category_map()["judo"].color
        services.log_session(
            workout.id, user.id, date.today(), 45,
            {workout.exercises[0].id: 30}, "good",
        )
    section = client.get("/analytics").data.decode()
    section = section[section.index("Repetitions per exercise") :]
    assert judo not in section
    assert f'title="{date.today().isoformat()}: 30' in section


def test_analytics_days_with_a_session_link_to_their_own_details(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        services.log_session(
            workout.id, user.id, date.today(), 45, {workout.exercises[0].id: 30}, "good"
        )
    html = client.get("/analytics").data.decode()
    activity = html[: html.index("Workouts performed")]
    today = date.today().isoformat()
    assert f'href="/analytics?day={today}#day"' in activity
    # a day with nothing on it is not a link, so only what opens looks clickable
    empty = (date.today() - timedelta(days=1)).isoformat()
    assert f"day={empty}" not in activity


def test_analytics_day_links_keep_the_selected_user(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        services.log_session(
            workout.id, user.id, date.today(), 45, {workout.exercises[0].id: 30}, "good"
        )
    html = client.get(f"/analytics?user_id={user.id}").data.decode()
    assert f'href="/analytics?user_id={user.id}&amp;day={date.today().isoformat()}#day"' in html


def test_analytics_day_shows_the_sessions_behind_a_cell(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat", "Lunge"], "judo")
        squat, lunge = workout.exercises
        services.log_session(
            workout.id, user.id, date(2026, 9, 1), 45,
            {squat.id: 30, lunge.id: 20}, "good",
            weights_by_exercise={squat.id: 40, lunge.id: services.NO_WEIGHT},
            extra_exercises=[("Pull-up", 12)],
            comment="Knee held up fine.",
        )
    html = client.get("/analytics?day=2026-09-01").data.decode()
    panel = html[html.index('class="day-detail"') : html.index("Workouts performed")]
    assert "Tuesday 01 Sep 2026" in panel
    assert "Judo" in panel and "Leg day" in panel and "45 min" in panel
    assert "felt good" in panel
    assert "3 exercises" in panel  # two of the workout plus the extra
    assert "62 repetitions" in panel  # 30 + 20 + 12
    assert "1200 kg moved" in panel  # only the squats carried anything
    assert "Squat" in panel and "Lunge" in panel and "Pull-up" in panel
    assert "bodyweight" in panel  # the lunges carried nothing
    assert "Knee held up fine." in panel


def test_analytics_day_marks_the_selected_cell(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        services.log_session(
            workout.id, user.id, date(2026, 9, 1), 45, {workout.exercises[0].id: 30},
            "good",
        )
    html = client.get("/analytics?day=2026-09-01").data.decode()
    activity = html[: html.index("Workouts performed")]
    assert 'class="cell level-4 selected"' in activity
    assert activity.count("selected") == 1  # one day is open at a time


def test_analytics_day_shows_sets_as_they_were_counted(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        services.log_session(
            workout.id, user.id, date(2026, 9, 1), 45, {workout.exercises[0].id: 12},
            "good", sets_by_exercise={workout.exercises[0].id: 4},
        )
    html = client.get("/analytics?day=2026-09-01").data.decode()
    assert "4 × 12 = 48" in html


def test_analytics_day_that_holds_nothing_says_so(client, app, user):
    with app.app_context():
        services.create_workout("Leg day", ["Squat"])
    html = client.get("/analytics?day=2026-09-01").data.decode()
    assert "Nothing logged on this day" in html


def test_analytics_day_is_narrowed_to_the_selected_user(client, app, user, other_user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        services.log_session(
            workout.id, other_user.id, date(2026, 9, 1), 45,
            {workout.exercises[0].id: 30}, "good",
        )
        alex, sam = user.id, other_user.id
    mine = client.get(f"/analytics?user_id={alex}&day=2026-09-01").data.decode()
    assert "Nothing logged on this day by Alex" in mine
    theirs = client.get(f"/analytics?user_id={sam}&day=2026-09-01").data.decode()
    assert "Nothing logged" not in theirs
    assert "Leg day" in theirs[theirs.index('class="day-detail"') :]


def test_analytics_day_names_the_user_only_across_everyone(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        services.log_session(
            workout.id, user.id, date(2026, 9, 1), 45, {workout.exercises[0].id: 30},
            "good",
        )
        user_id = user.id
    everyone = client.get("/analytics?day=2026-09-01").data.decode()
    panel = everyone[everyone.index('class="day-detail"') : everyone.index("Workouts performed")]
    assert "Alex" in panel
    mine = client.get(f"/analytics?user_id={user_id}&day=2026-09-01").data.decode()
    panel = mine[mine.index('class="day-detail"') : mine.index("Workouts performed")]
    assert "Alex" not in panel  # the page already says whose day it is


def test_analytics_user_filter_keeps_the_open_day(client, app, user):
    html = client.get("/analytics?day=2026-09-01").data.decode()
    form = html[html.index('class="user-filter"') : html.index("</form>")]
    assert '<input type="hidden" name="day" value="2026-09-01">' in form


def test_analytics_without_a_day_invites_a_click(client):
    html = client.get("/analytics").data.decode()
    assert "Pick a day on the map" in html
    assert 'class="day-detail"' not in html


def test_analytics_ignores_an_unparseable_day(client, app, user):
    """Only reachable by hand: it renders the page without the panel."""
    response = client.get("/analytics?day=not-a-date")
    assert response.status_code == 200
    assert b"Pick a day on the map" in response.data


def test_analytics_page_sections_are_ordered(client):
    html = client.get("/analytics").data.decode()
    assert (
        html.index("Activity, last 12 months")
        < html.index("Workouts performed")
        < html.index("How it felt")
        < html.index("Repetitions per exercise")
        < html.index("Session comments")
    )


def test_analytics_page_renders_on_empty_db(client):
    response = client.get("/analytics")
    assert response.status_code == 200
    assert b"No sessions in this period yet" in response.data


def test_analytics_page_shows_total_workouts_above_the_table(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        for day in (date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)):
            services.log_session(workout.id, user.id, day, 45, {workout.exercises[0].id: 10}, "good")
    html = client.get("/analytics").data.decode()
    stat = html.index("3 <span>workouts performed in total</span>")
    assert html.index("Workouts performed") < stat < html.index("<table")


def test_analytics_page_total_workouts_is_singular_for_one(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        services.log_session(workout.id, user.id, date(2026, 9, 1), 45, {workout.exercises[0].id: 10}, "good")
    html = client.get("/analytics").data.decode()
    assert "1 <span>workout performed in total</span>" in html


def test_analytics_workouts_table_shows_the_feeling_breakdown(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        reps = {workout.exercises[0].id: 10}
        services.log_session(workout.id, user.id, date(2026, 9, 1), 45, reps, "good")
        services.log_session(workout.id, user.id, date(2026, 9, 2), 45, reps, "good")
        services.log_session(workout.id, user.id, date(2026, 9, 3), 45, reps, "bad")
    html = client.get("/analytics").data.decode()
    table = html[html.index("<table") : html.index("</table>")]
    for heading in ("Good", "Okay", "Bad"):
        assert f"<th>{heading}</th>" in table
    start = table.index("<td>Leg day</td>")
    row = table[start : table.index("</tr>", start)]
    cells = re.findall(r"<td[^>]*>([^<]*)</td>", row)
    # workout, times done, good, okay, bad
    assert cells == ["Leg day", "3", "2", "0", "1"]


def test_analytics_page_draws_a_heatmap_per_exercise(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat", "Lunge"])
        services.log_session(
            workout.id,
            user.id, date.today(), 45,
            {m.id: v for m, v in zip(workout.exercises, (30, 20))}, "good",
        )
    html = client.get("/analytics").data.decode()
    section = html[html.index("Repetitions per exercise") :]
    assert section.count('class="heatmap"') == 2  # one per exercise
    assert "<h3>Squat" in section and "<h3>Lunge" in section
    assert f'title="{date.today().isoformat()}: 30 repetitions"' in section
    assert f'title="{date.today().isoformat()}: 20 repetitions"' in section
    assert "<td>Squat</td>" not in section  # no table any more


def test_analytics_heatmaps_are_labelled_with_month_and_year(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        services.log_session(workout.id, user.id, date.today(), 45, {workout.exercises[0].id: 30}, "good")
    html = client.get("/analytics").data.decode()
    this_month = date.today().strftime("%b %Y")
    a_year_ago = (date.today() - timedelta(days=364)).strftime("%b %Y")
    # once for the activity map, once for the exercise's own heatmap
    assert html.count('class="heatmap-months"') == 2
    for section in (html[: html.index("Repetitions per exercise")],
                    html[html.index("Repetitions per exercise") :]):
        assert f">{this_month}</span>" in section
        assert f">{a_year_ago}</span>" in section
        assert 'class="heatmap-month" style="--weeks:' in section


def test_analytics_exercise_heatmap_shades_the_best_day_darkest(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        exercise_id = workout.exercises[0].id
        services.log_session(workout.id, user.id, date.today(), 45, {exercise_id: 30}, "good")
        services.log_session(
            workout.id,
            user.id, date.today() - timedelta(days=1), 45, {exercise_id: 5}, "good"
        )
    html = client.get("/analytics").data.decode()
    section = html[html.index("Repetitions per exercise") :]
    today, yesterday = date.today(), date.today() - timedelta(days=1)
    assert f'class="cell level-4" title="{today.isoformat()}: 30' in section
    assert f'class="cell level-1" title="{yesterday.isoformat()}: 5' in section


def test_analytics_page_notes_exercises_never_performed(client, app):
    with app.app_context():
        services.create_workout("Core day", ["Plank"])
    html = client.get("/analytics").data.decode()
    section = html[html.index("Repetitions per exercise") :]
    assert "<h3>Plank</h3>" in section
    assert "Not performed yet" in section
    assert 'class="heatmap"' not in section


def test_analytics_page_badges_each_exercises_trend(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Rising", "Falling", "Zero"])
        ids = {m.name: m.id for m in workout.exercises}
        for week, (up, down) in enumerate(((5, 40), (20, 25), (35, 10))):
            services.log_session(
                workout.id,
                user.id,
                date.today() - timedelta(weeks=2 - week),
                45,
                {ids["Rising"]: up, ids["Falling"]: down, ids["Zero"]: 0},
                "good",
            )
    html = client.get("/analytics").data.decode()
    section = html[html.index("Repetitions per exercise") :]
    assert '<h3>Rising<span class="trend trend-up"' in section
    assert "↑ going up" in section
    assert '<h3>Falling<span class="trend trend-down"' in section
    assert "↓ going down" in section
    # 'Zero' is 0 in every session: no change either way
    assert '<h3>Zero<span class="trend trend-similar"' in section
    assert "→ holding steady" in section


def test_analytics_page_omits_the_trend_when_there_is_one_date(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        services.log_session(workout.id, user.id, date.today(), 45, {workout.exercises[0].id: 30}, "good")
    html = client.get("/analytics").data.decode()
    section = html[html.index("Repetitions per exercise") :]
    assert "<h3>Squat</h3>" in section
    assert 'class="trend' not in section


def test_analytics_trend_badge_shows_the_percentage_change(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        exercise_id = workout.exercises[0].id
        services.log_session(
            workout.id,
            user.id, date.today() - timedelta(days=2), 45, {exercise_id: 20}, "good"
        )
        services.log_session(workout.id, user.id, date.today(), 45, {exercise_id: 30}, "good")
    html = client.get("/analytics").data.decode()
    assert "↑ going up (+50%)" in html


def test_analytics_page_offers_a_user_dropdown(client, app):
    with app.app_context():
        services.create_user("Alex", 34)
        services.create_user("Sam", 41)
    html = client.get("/analytics").data.decode()
    assert 'name="user_id"' in html
    assert ">All users</option>" in html
    assert ">Alex</option>" in html and ">Sam</option>" in html
    assert "across all users" in html


def test_analytics_page_for_one_user_selects_them_in_the_dropdown(client, app):
    with app.app_context():
        alex = services.create_user("Alex", 34)
        alex_id = alex.id
    html = client.get(f"/analytics?user_id={alex_id}").data.decode()
    assert f'value="{alex_id}" selected' in html
    assert "Everything Alex (34) has logged" in html


def test_analytics_page_shows_only_the_selected_users_numbers(client, app):
    with app.app_context():
        alex = services.create_user("Alex", 34)
        sam = services.create_user("Sam", 41)
        workout = services.create_workout("Leg day", ["Squat"])
        reps = {workout.exercises[0].id: 30}
        services.log_session(workout.id, alex.id, date.today(), 45, reps, "good")
        services.log_session(
            workout.id, sam.id, date.today() - timedelta(days=1), 45,
            {workout.exercises[0].id: 5}, "bad",
        )
        alex_id, sam_id = alex.id, sam.id

    everyone = client.get("/analytics").data.decode()
    assert "2 <span>workouts performed in total</span>" in everyone
    assert "35 <span>repetitions in total</span>" in everyone

    mine = client.get(f"/analytics?user_id={alex_id}").data.decode()
    assert "1 <span>workout performed in total</span>" in mine
    assert "30 <span>repetitions in total</span>" in mine

    theirs = client.get(f"/analytics?user_id={sam_id}").data.decode()
    assert "1 <span>workout performed in total</span>" in theirs
    assert "5 <span>repetitions in total</span>" in theirs


def test_analytics_page_for_a_user_omits_what_they_never_did(client, app):
    with app.app_context():
        alex = services.create_user("Alex", 34)
        workout = services.create_workout("Leg day", ["Squat"])
        services.create_workout("Core day", ["Plank"])  # nobody has done this one
        services.log_session(
            workout.id, alex.id, date.today(), 45, {workout.exercises[0].id: 30}, "good"
        )
        alex_id = alex.id

    html = client.get(f"/analytics?user_id={alex_id}").data.decode()
    table = html[html.index("<table") : html.index("</table>")]
    assert "<td>Leg day</td>" in table
    assert "Core day" not in table
    # and the same for the exercise breakdown below it
    assert "<h3>Squat" in html
    assert "Plank" not in html
    assert "Not performed yet" not in html

    everyone = client.get("/analytics").data.decode()
    assert "<td>Core day</td>" in everyone[: everyone.index("</table>")]
    assert "<h3>Plank</h3>" in everyone
    assert "Not performed yet" in everyone


def test_analytics_page_tells_a_user_with_no_sessions_to_track_one(client, app):
    with app.app_context():
        alex = services.create_user("Alex", 34)
        services.create_workout("Core day", ["Plank"])
        alex_id = alex.id
    html = client.get(f"/analytics?user_id={alex_id}").data.decode()
    assert "Alex hasn't performed a workout yet" in html
    assert "Alex hasn't performed an exercise yet" in html
    assert "<table" not in html
    # the activity map at the top always renders; the exercise grids do not
    assert 'class="heatmap"' not in html[html.index("Repetitions per exercise") :]
    # across everyone the workout and its exercise still show up, at zero
    everyone = client.get("/analytics").data.decode()
    assert "<td>Core day</td>" in everyone
    assert "<h3>Plank</h3>" in everyone


def test_analytics_page_falls_back_to_everyone_for_an_unknown_user(client, app):
    for query in ("?user_id=999", "?user_id=", "?user_id=nonsense"):
        html = client.get("/analytics" + query).data.decode()
        assert "across all users" in html


def test_analytics_page_does_not_label_an_extra_with_another_workout(client, app, user):
    with app.app_context():
        services.create_workout("Leg day", ["Squats"])
        arms = services.create_workout("Arm day", ["Push ups"])
        services.log_session(
            arms.id, user.id, date(2026, 9, 9), 45, {arms.exercises[0].id: 10},
            "good", extra_exercises=[("Squats", 20)],
        )
    html = client.get("/analytics").data.decode()
    section = html[html.index("Repetitions per exercise") :]
    block = section[section.index("<h3>Squats") :]
    caption = block[block.index('class="chart-caption"') : block.index("</p>")]
    assert "extra, this session only" in caption
    assert "Leg day" not in caption


def test_analytics_page_shows_the_weight_moved_per_exercise(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        exercise_id = workout.exercises[0].id
        services.log_session(
            workout.id, user.id, date(2026, 9, 1), 45, {exercise_id: 10}, "good",
            weights_by_exercise={exercise_id: 20},
        )
        services.log_session(
            workout.id, user.id, date(2026, 9, 3), 45, {exercise_id: 10}, "good",
            weights_by_exercise={exercise_id: 40},
        )
    html = client.get("/analytics").data.decode()
    section = html[html.index("Repetitions per exercise") :]
    unit = services.WEIGHT_UNIT
    assert f"600 <span>{unit} moved in total</span>" in section  # 200 + 400
    start = section.index('class="chart-caption"')
    caption = flat(section[start : section.index("</p>", start)])
    assert "20 repetitions" in caption
    assert f"600 {unit} moved" in caption
    assert f"best session 400 {unit} on 03 Sep 2026" in caption
    # the repetitions come first, then the weight, then the best session
    assert (
        caption.index("repetitions")
        < caption.index(f"600 {unit} moved")
        < caption.index("best session")
    )


def test_analytics_page_reports_a_bodyweight_exercise_in_repetitions_alone(
    client, app, user
):
    """Nothing was carried, so there is no weight clause and no total to show."""
    with app.app_context():
        workout = services.create_workout("Core day", ["Plank"])
        services.log_session(
            workout.id, user.id, date(2026, 9, 1), 45,
            {workout.exercises[0].id: 30}, "good",
        )
    html = client.get("/analytics").data.decode()
    section = html[html.index("Repetitions per exercise") :]
    start = section.index('class="chart-caption"')
    caption = flat(section[start : section.index("</p>", start)])
    assert "30 repetitions across 1 session" in caption
    assert f"{services.WEIGHT_UNIT} moved" not in caption
    assert "best session" not in caption
    assert f"{services.WEIGHT_UNIT} moved in total" not in section
    assert "30 <span>repetitions in total</span>" in section


def test_analytics_page_keeps_the_weight_total_when_anything_was_carried(
    client, app, user
):
    """One weighted exercise alongside a bodyweight one still totals a weight."""
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat", "Plank"])
        squat, plank = (m.id for m in workout.exercises)
        services.log_session(
            workout.id, user.id, date(2026, 9, 1), 45, {squat: 10, plank: 30},
            "good", weights_by_exercise={squat: 20},
        )
    html = client.get("/analytics").data.decode()
    section = html[html.index("Repetitions per exercise") :]
    unit = services.WEIGHT_UNIT
    assert f"200 <span>{unit} moved in total</span>" in section
    plank_block = section[section.index("<h3>Plank") :]
    plank_caption = flat(
        plank_block[: plank_block.index("</p>", plank_block.index("chart-caption"))]
    )
    assert f"{unit} moved" not in plank_caption
    assert "best session" not in plank_caption


def test_analytics_page_says_nothing_about_weight_for_an_unperformed_exercise(
    client, app
):
    with app.app_context():
        services.create_workout("Core day", ["Plank"])
    html = client.get("/analytics").data.decode()
    section = html[html.index("Repetitions per exercise") :]
    assert "Not performed yet" in section
    assert "best session" not in section


def test_analytics_page_weight_is_per_user(client, app):
    with app.app_context():
        alex = services.create_user("Alex", 34)
        sam = services.create_user("Sam", 41)
        workout = services.create_workout("Leg day", ["Squat"])
        exercise_id = workout.exercises[0].id
        services.log_session(
            workout.id, alex.id, date(2026, 9, 1), 45, {exercise_id: 10}, "good",
            weights_by_exercise={exercise_id: 20},
        )
        services.log_session(
            workout.id, sam.id, date(2026, 9, 2), 45, {exercise_id: 10}, "good",
            weights_by_exercise={exercise_id: 100},
        )
        alex_id = alex.id
    unit = services.WEIGHT_UNIT
    everyone = client.get("/analytics").data.decode()
    assert f"1200 <span>{unit} moved in total</span>" in everyone
    mine = client.get(f"/analytics?user_id={alex_id}").data.decode()
    assert f"200 <span>{unit} moved in total</span>" in mine
    assert f"best session 200 {unit} on 01 Sep 2026" in flat(mine)


def test_analytics_page_lists_session_comments_last(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        services.log_session(
            workout.id, user.id, date(2026, 9, 1), 45,
            {workout.exercises[0].id: 30}, "bad", comment="Shoulder twinge.",
        )
    html = client.get("/analytics").data.decode()
    section = html[html.index("Session comments") :]
    assert "Shoulder twinge." in section
    assert "01 Sep 2026" in section  # the date
    assert "Leg day" in section  # the workout
    assert "felt bad" in section  # the feeling
    assert 'class="swatch swatch-bad"' in section


def test_analytics_page_orders_comments_newest_first(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        reps = {workout.exercises[0].id: 10}
        for day, note in ((date(2026, 9, 1), "Older."), (date(2026, 9, 5), "Newer.")):
            services.log_session(
                workout.id, user.id, day, 45, reps, "good", comment=note
            )
    section = client.get("/analytics").data.decode()
    section = section[section.index("Session comments") :]
    assert section.index("Newer.") < section.index("Older.")


def test_analytics_page_lists_only_the_last_few_comments(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        squat = workout.exercises[0].id
        for day in range(1, 9):
            services.log_session(
                workout.id, user.id, date(2026, 9, day), 45, {squat: 10}, "good",
                comment=f"Note {day}.",
            )
    html = client.get("/analytics").data.decode()
    section = html[html.index("Session comments") :]
    assert f"The last {services.COMMENT_LIMIT} notes" in section
    for day in (8, 7, 6, 5, 4):
        assert f"Note {day}." in section
    for day in (3, 2, 1):
        assert f"Note {day}." not in section
    assert section.count("<li>") == services.COMMENT_LIMIT


def test_analytics_page_names_the_commenter_only_across_everyone(client, app):
    with app.app_context():
        alex = services.create_user("Alex", 34)
        workout = services.create_workout("Leg day", ["Squat"])
        services.log_session(
            workout.id, alex.id, date(2026, 9, 1), 45,
            {workout.exercises[0].id: 30}, "good", comment="Felt strong.",
        )
        alex_id = alex.id

    everyone = client.get("/analytics").data.decode()
    everyone = everyone[everyone.index("Session comments") :]
    assert "Felt strong." in everyone and "Alex" in everyone

    mine = client.get(f"/analytics?user_id={alex_id}").data.decode()
    mine = mine[mine.index("Session comments") :]
    assert "Felt strong." in mine
    assert "Alex" not in mine  # the page already says whose it is


def test_analytics_page_says_when_there_are_no_comments(client, app, user):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        services.log_session(
            workout.id, user.id, date(2026, 9, 1), 45,
            {workout.exercises[0].id: 30}, "good",
        )
        user_id = user.id
    html = client.get("/analytics").data.decode()
    assert "No comments yet" in html
    mine = client.get(f"/analytics?user_id={user_id}").data.decode()
    assert "Alex hasn't left a comment yet" in mine
