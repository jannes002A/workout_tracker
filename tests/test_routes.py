import re
from datetime import date, timedelta

from src import services
from src.models import SessionMovement, Workout, WorkoutSession


def test_index_redirects_to_create(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/create" in response.headers["Location"]


# --------------------------------------------------------------- create page


def test_create_page_renders(client):
    response = client.get("/create")
    assert response.status_code == 200
    assert b"Create a workout" in response.data


def test_create_workout_via_form(client, app):
    response = client.post(
        "/create",
        data={"name": "Leg day", "movements": ["Squat", "Lunge", ""]},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"saved" in response.data
    with app.app_context():
        workout = Workout.query.one()
        assert workout.name == "Leg day"
        assert len(workout.movements) == 2


def test_create_page_offers_known_movements(client, app):
    with app.app_context():
        services.create_workout("Leg day", ["Squat", "Lunge"])
        workout = services.create_workout("Push day", ["Bench press", "Squat"])
        services.log_session(
            workout.id,
            date(2026, 9, 1),
            45,
            {m.id: 10 for m in workout.movements},
            "good",
            extra_movements=[("Pull-up", 12)],
        )
    html = client.get("/create").data.decode()
    assert "Or select a movement you've already used" in html
    for name in ("Squat", "Lunge", "Bench press", "Pull-up"):
        assert f'data-movement="{name}"' in html
    assert html.count('data-movement="Squat"') == 1  # listed once, not per workout


def test_create_page_has_no_picker_when_no_movements_exist(client):
    html = client.get("/create").data.decode()
    assert 'data-movement="' not in html  # the chips; the click handler stays
    assert "Or select a movement" not in html


def test_create_workout_from_picked_movements(client, app):
    """The picker just fills in movements fields, so the POST looks the same."""
    with app.app_context():
        services.create_workout("Leg day", ["Squat"])
    client.post(
        "/create",
        data={"name": "Leg day 2", "movements": ["Squat", "Squat", "Lunge"]},
        follow_redirects=True,
    )
    with app.app_context():
        workout = Workout.query.filter_by(name="Leg day 2").one()
        assert [m.name for m in workout.movements] == ["Squat", "Lunge"]


def test_create_workout_form_shows_validation_error(client):
    response = client.post("/create", data={"name": "", "movements": ["Squat"]})
    assert b"Workout name is required." in response.data


# ---------------------------------------------------------------- track page


def track_form(workout, reps, **overrides):
    """POST data for /track: one reps-<movement id> field per movement."""
    data = {
        "workout_id": workout.id,
        "date": "2026-09-01",
        "duration": "45",
        "feeling": "good",
    }
    data.update({f"reps-{m.id}": str(v) for m, v in zip(workout.movements, reps)})
    data.update(overrides)
    return data


def test_track_page_contains_all_dropdowns(client, app):
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


def test_track_page_lists_every_movement_of_every_workout(client, app):
    with app.app_context():
        legs = services.create_workout("Leg day", ["Squat", "Lunge"])
        push = services.create_workout("Push day", ["Bench press"])
        ids = [m.id for m in legs.movements + push.movements]
        names = [m.name for m in legs.movements + push.movements]
    html = client.get("/track").data.decode()
    for name in names:
        assert name in html
    for movement_id in ids:
        assert f'name="reps-{movement_id}"' in html


def test_track_session_via_form(client, app):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat", "Lunge"])
        data = track_form(workout, (30, 20))
    response = client.post("/track", data=data, follow_redirects=True)
    assert b"Logged Leg day" in response.data
    assert b"50 repetitions" in response.data
    with app.app_context():
        session = WorkoutSession.query.one()
        assert session.date == date(2026, 9, 1)
        assert session.duration_minutes == 45
        assert {log.movement.name: log.repetitions for log in session.logs} == {
            "Squat": 30,
            "Lunge": 20,
        }


def test_track_session_ignores_other_workouts_movement_fields(client, app):
    """Without JS the form submits every workout's fields; only one counts."""
    with app.app_context():
        legs = services.create_workout("Leg day", ["Squat"])
        push = services.create_workout("Push day", ["Bench press"])
        data = track_form(legs, (30,))
        data[f"reps-{push.movements[0].id}"] = "99"
    client.post("/track", data=data, follow_redirects=True)
    with app.app_context():
        log = SessionMovement.query.one()
        assert log.repetitions == 30
        assert log.movement.name == "Squat"


def test_track_session_missing_movement_shows_error(client, app):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat", "Lunge"])
        data = track_form(workout, (30, 20))
        del data[f"reps-{workout.movements[1].id}"]
    response = client.post("/track", data=data)
    assert b"Enter repetitions for &#39;Lunge&#39;." in response.data
    with app.app_context():
        assert WorkoutSession.query.count() == 0


def test_track_session_invalid_input_shows_error(client, app):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, (30,), feeling="amazing")
    response = client.post("/track", data=data)
    assert b"Feeling must be good, okay or bad." in response.data
    with app.app_context():
        assert WorkoutSession.query.count() == 0


def test_track_session_out_of_range_repetitions_shows_error(client, app):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, (500,))
    response = client.post("/track", data=data)
    assert b"must be between 0 and 120" in response.data
    with app.app_context():
        assert WorkoutSession.query.count() == 0


def test_track_page_offers_an_extra_movement_row(client, app):
    with app.app_context():
        services.create_workout("Leg day", ["Squat"])
    html = client.get("/track").data.decode()
    assert 'name="extra-name"' in html
    assert 'name="extra-reps"' in html
    assert "addExtraMovement()" in html
    assert 'id="extra-row-template"' in html  # cloned by the button


def test_track_session_with_extra_movement_via_form(client, app):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, (30,))
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
        assert Workout.query.one().movements[0].name == "Squat"  # workout untouched


def test_track_session_ignores_blank_extra_movement_row(client, app):
    """The form always renders one empty row; leaving it alone logs nothing."""
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, (30,))
        data["extra-name"] = ""
        data["extra-reps"] = "10"
    client.post("/track", data=data, follow_redirects=True)
    with app.app_context():
        assert SessionMovement.query.count() == 1  # just the Squat


def test_track_session_with_several_extra_movements_via_form(client, app):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, (30,))
    data = {**data, "extra-name": ["Pull-up", "", "Dip"], "extra-reps": ["12", "10", "8"]}
    client.post("/track", data=data, follow_redirects=True)
    with app.app_context():
        session = WorkoutSession.query.one()
        assert {log.name: log.repetitions for log in session.logs} == {
            "Squat": 30,
            "Pull-up": 12,
            "Dip": 8,
        }


def test_track_session_extra_already_in_workout_shows_error(client, app):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        data = track_form(workout, (30,))
        data["extra-name"] = "squat"
        data["extra-reps"] = "12"
    response = client.post("/track", data=data)
    assert b"already a movement of Leg day" in response.data
    with app.app_context():
        assert WorkoutSession.query.count() == 0


# ------------------------------------------------------------ analytics page


def test_analytics_page_renders_with_data(client, app):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat", "Lunge"])
        reps = {m.id: v for m, v in zip(workout.movements, (30, 20))}
        services.log_session(workout.id, date.today(), 45, reps, "good")
    html = client.get("/analytics").data.decode()
    assert "Activity, last 12 months" in html
    assert "heatmap" in html
    assert "Workouts performed" in html
    assert "Leg day" in html
    assert "Repetitions per movement" in html
    assert "Squat" in html and "Lunge" in html
    assert "50 " in html  # total repetitions across both movements
    assert "feeling-chart" in html
    assert "bar-good" in html


def test_analytics_page_lists_extra_movements(client, app):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        services.log_session(
            workout.id,
            date.today(),
            45,
            {workout.movements[0].id: 30},
            "good",
            extra_movements=[("Pull-up", 12)],
        )
    html = client.get("/analytics").data.decode()
    assert "Pull-up" in html
    assert "extra, this session only" in html
    assert "42 " in html  # grand total includes the extra


def test_analytics_page_sections_are_ordered(client):
    html = client.get("/analytics").data.decode()
    assert (
        html.index("Activity, last 12 months")
        < html.index("Workouts performed")
        < html.index("How it felt")
        < html.index("Repetitions per movement")
    )


def test_analytics_page_renders_on_empty_db(client):
    response = client.get("/analytics")
    assert response.status_code == 200
    assert b"No sessions in this period yet" in response.data


def test_analytics_page_shows_total_workouts_above_the_table(client, app):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        for day in (date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)):
            services.log_session(workout.id, day, 45, {workout.movements[0].id: 10}, "good")
    html = client.get("/analytics").data.decode()
    stat = html.index("3 <span>workouts performed in total</span>")
    assert html.index("Workouts performed") < stat < html.index("<table")


def test_analytics_page_total_workouts_is_singular_for_one(client, app):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        services.log_session(workout.id, date(2026, 9, 1), 45, {workout.movements[0].id: 10}, "good")
    html = client.get("/analytics").data.decode()
    assert "1 <span>workout performed in total</span>" in html


def test_analytics_workouts_table_shows_the_feeling_breakdown(client, app):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        reps = {workout.movements[0].id: 10}
        services.log_session(workout.id, date(2026, 9, 1), 45, reps, "good")
        services.log_session(workout.id, date(2026, 9, 2), 45, reps, "good")
        services.log_session(workout.id, date(2026, 9, 3), 45, reps, "bad")
    html = client.get("/analytics").data.decode()
    table = html[html.index("<table") : html.index("</table>")]
    for heading in ("Good", "Okay", "Bad"):
        assert f"<th>{heading}</th>" in table
    start = table.index("<td>Leg day</td>")
    row = table[start : table.index("</tr>", start)]
    cells = re.findall(r"<td[^>]*>([^<]*)</td>", row)
    # workout, times done, good, okay, bad
    assert cells == ["Leg day", "3", "2", "0", "1"]


def test_analytics_page_draws_a_heatmap_per_movement(client, app):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat", "Lunge"])
        services.log_session(
            workout.id, date.today(), 45,
            {m.id: v for m, v in zip(workout.movements, (30, 20))}, "good",
        )
    html = client.get("/analytics").data.decode()
    section = html[html.index("Repetitions per movement") :]
    assert section.count('class="heatmap"') == 2  # one per movement
    assert "<h3>Squat" in section and "<h3>Lunge" in section
    assert f'title="{date.today().isoformat()}: 30 repetitions"' in section
    assert f'title="{date.today().isoformat()}: 20 repetitions"' in section
    assert "<td>Squat</td>" not in section  # no table any more


def test_analytics_heatmaps_are_labelled_with_month_and_year(client, app):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        services.log_session(workout.id, date.today(), 45, {workout.movements[0].id: 30}, "good")
    html = client.get("/analytics").data.decode()
    this_month = date.today().strftime("%b %Y")
    a_year_ago = (date.today() - timedelta(days=364)).strftime("%b %Y")
    # once for the activity map, once for the movement's own heatmap
    assert html.count('class="heatmap-months"') == 2
    for section in (html[: html.index("Repetitions per movement")],
                    html[html.index("Repetitions per movement") :]):
        assert f">{this_month}</span>" in section
        assert f">{a_year_ago}</span>" in section
        assert 'class="heatmap-month" style="--weeks:' in section


def test_analytics_movement_heatmap_shades_the_best_day_darkest(client, app):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        movement_id = workout.movements[0].id
        services.log_session(workout.id, date.today(), 45, {movement_id: 30}, "good")
        services.log_session(
            workout.id, date.today() - timedelta(days=1), 45, {movement_id: 5}, "good"
        )
    html = client.get("/analytics").data.decode()
    section = html[html.index("Repetitions per movement") :]
    today, yesterday = date.today(), date.today() - timedelta(days=1)
    assert f'class="cell level-4" title="{today.isoformat()}: 30' in section
    assert f'class="cell level-1" title="{yesterday.isoformat()}: 5' in section


def test_analytics_page_notes_movements_never_performed(client, app):
    with app.app_context():
        services.create_workout("Core day", ["Plank"])
    html = client.get("/analytics").data.decode()
    section = html[html.index("Repetitions per movement") :]
    assert "<h3>Plank</h3>" in section
    assert "Not performed yet" in section
    assert 'class="heatmap"' not in section


def test_analytics_page_badges_each_movements_trend(client, app):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Rising", "Falling", "Zero"])
        ids = {m.name: m.id for m in workout.movements}
        for week, (up, down) in enumerate(((5, 40), (20, 25), (35, 10))):
            services.log_session(
                workout.id,
                date.today() - timedelta(weeks=2 - week),
                45,
                {ids["Rising"]: up, ids["Falling"]: down, ids["Zero"]: 0},
                "good",
            )
    html = client.get("/analytics").data.decode()
    section = html[html.index("Repetitions per movement") :]
    assert '<h3>Rising<span class="trend trend-up"' in section
    assert "↑ going up" in section
    assert '<h3>Falling<span class="trend trend-down"' in section
    assert "↓ going down" in section
    # 'Zero' is 0 in every session: no change either way
    assert '<h3>Zero<span class="trend trend-similar"' in section
    assert "→ holding steady" in section


def test_analytics_page_omits_the_trend_when_there_is_one_date(client, app):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        services.log_session(workout.id, date.today(), 45, {workout.movements[0].id: 30}, "good")
    html = client.get("/analytics").data.decode()
    section = html[html.index("Repetitions per movement") :]
    assert "<h3>Squat</h3>" in section
    assert 'class="trend' not in section


def test_analytics_trend_badge_shows_the_percentage_change(client, app):
    with app.app_context():
        workout = services.create_workout("Leg day", ["Squat"])
        movement_id = workout.movements[0].id
        services.log_session(
            workout.id, date.today() - timedelta(days=2), 45, {movement_id: 20}, "good"
        )
        services.log_session(workout.id, date.today(), 45, {movement_id: 30}, "good")
    html = client.get("/analytics").data.decode()
    assert "↑ going up (+50%)" in html
