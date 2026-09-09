from datetime import date, timedelta

import pytest

from src import services


@pytest.fixture()
def seeded(app):
    """Two workouts sharing the 'Squat' movement, with three sessions logged."""
    legs = services.create_workout("Leg day", ["Squat", "Lunge"])
    push = services.create_workout("Push day", ["Bench press", "Squat"])
    reps = {m.id: v for m, v in zip(legs.movements, (30, 20))}
    services.log_session(legs.id, date(2026, 9, 1), 45, reps, "good")
    services.log_session(legs.id, date(2026, 9, 3), 30, reps, "okay")
    services.log_session(
        push.id,
        date(2026, 9, 3),
        60,
        {m.id: v for m, v in zip(push.movements, (10, 5))},
        "bad",
    )
    return {"legs": legs, "push": push}


# --------------------------------------------------------------- activity_map


def test_activity_map_shape(app):
    end = date(2026, 9, 8)
    data = services.activity_map(end=end, days=365)
    cells = [c for week in data["weeks"] for c in week if c]
    assert len(cells) == 365
    assert all(len(week) == 7 for week in data["weeks"])
    assert cells[0]["date"] == (end - timedelta(days=364)).isoformat()
    assert cells[-1]["date"] == end.isoformat()


def test_activity_map_counts_and_levels(app, seeded):
    data = services.activity_map(end=date(2026, 9, 8), days=30)
    by_date = {c["date"]: c for week in data["weeks"] for c in week if c}
    assert by_date["2026-09-01"]["count"] == 1
    assert by_date["2026-09-03"]["count"] == 2
    assert by_date["2026-09-02"]["count"] == 0
    assert by_date["2026-09-02"]["level"] == 0
    assert by_date["2026-09-03"]["level"] == 4  # busiest day gets top level
    assert data["max"] == 2


def test_activity_map_empty_db_all_level_zero(app):
    data = services.activity_map(end=date(2026, 9, 8), days=14)
    cells = [c for week in data["weeks"] for c in week if c]
    assert all(c["count"] == 0 and c["level"] == 0 for c in cells)
    assert data["max"] == 0


def test_activity_map_labels_each_month_of_the_x_axis(app):
    data = services.activity_map(end=date(2026, 9, 8), days=365)
    labels = [month["label"] for month in data["months"]]
    assert labels[0] == "Sep 2025"   # the window opens in the previous year
    assert labels[-1] == "Sep 2026"  # and closes in the current one
    assert labels[:4] == ["Sep 2025", "Oct 2025", "Nov 2025", "Dec 2025"]
    assert len(labels) == 13  # 12 months plus the re-entered start month
    assert labels == sorted(set(labels), key=labels.index)  # no month repeats


def test_activity_map_month_spans_cover_every_week_column(app):
    data = services.activity_map(end=date(2026, 9, 8), days=365)
    assert sum(month["weeks"] for month in data["months"]) == len(data["weeks"])


def test_activity_map_month_label_starts_at_its_first_week(app):
    data = services.activity_map(end=date(2026, 9, 8), days=365)
    column = 0
    for month in data["months"]:
        first_day = next(c for c in data["weeks"][column] if c)["date"]
        assert date.fromisoformat(first_day).strftime("%b %Y") == month["label"]
        column += month["weeks"]


def test_activity_map_weeks_start_monday(app):
    # 2026-09-08 is a Tuesday; first cell of a full week must be a Monday.
    data = services.activity_map(end=date(2026, 9, 8), days=365)
    first_full_week = next(w for w in data["weeks"] if all(w))
    assert date.fromisoformat(first_full_week[0]["date"]).weekday() == 0


# ---------------------------------------------------------- workout_frequency


def test_workout_frequency_counts_and_order(app, seeded):
    freq = services.workout_frequency()
    assert [(row["name"], row["count"]) for row in freq] == [
        ("Leg day", 2),
        ("Push day", 1),
    ]


def test_workout_frequency_reports_how_each_workout_felt(app, seeded):
    by_name = {row["name"]: row for row in services.workout_frequency()}
    # Leg day was logged 'good' once and 'okay' once; Push day 'bad' once.
    assert by_name["Leg day"]["feelings"] == {"good": 1, "okay": 1, "bad": 0}
    assert by_name["Push day"]["feelings"] == {"good": 0, "okay": 0, "bad": 1}


def test_workout_frequency_feelings_sum_to_the_count(app, seeded):
    for row in services.workout_frequency():
        assert sum(row["feelings"].values()) == row["count"]


def test_workout_frequency_includes_untracked_workouts(app):
    services.create_workout("Core day", ["Plank"])
    assert services.workout_frequency() == [
        {
            "name": "Core day",
            "count": 0,
            "feelings": {"good": 0, "okay": 0, "bad": 0},
        }
    ]


def test_workout_frequency_empty_db(app):
    assert services.workout_frequency() == []


# ------------------------------------------------------- movement_repetitions


def test_movement_repetitions_totals_and_order(app, seeded):
    rows = services.movement_repetitions()
    by_name = {row["name"]: row for row in rows}
    # Squat: 30 in each of the two Leg day sessions, plus 5 in Push day.
    assert by_name["Squat"]["repetitions"] == 65
    assert by_name["Squat"]["times"] == 3
    assert by_name["Lunge"]["repetitions"] == 40  # 20 in each Leg day session
    assert by_name["Bench press"]["repetitions"] == 10
    assert [row["name"] for row in rows] == ["Squat", "Lunge", "Bench press"]


def test_movement_repetitions_merges_same_movement_across_workouts(app, seeded):
    squat = next(r for r in services.movement_repetitions() if r["name"] == "Squat")
    assert squat["workouts"] == ["Leg day", "Push day"]


def test_movement_repetitions_includes_never_performed_movements(app):
    services.create_workout("Core day", ["Plank"])
    assert services.movement_repetitions() == [
        {
            "name": "Plank",
            "repetitions": 0,
            "times": 0,
            "workouts": ["Core day"],
            "extra": False,
            "heatmap": None,
            "trend": {
                "direction": None,
                "early": 0,
                "late": 0,
                "change": None,
                "split": None,
            },
        }
    ]


def test_movement_repetitions_empty_db(app):
    assert services.movement_repetitions() == []


def test_movement_repetitions_includes_extra_movements(app, seeded):
    legs = seeded["legs"]
    services.log_session(
        legs.id,
        date(2026, 9, 5),
        45,
        {m.id: 10 for m in legs.movements},
        "good",
        extra_movements=[("Pull-up", 12)],
    )
    pullup = next(r for r in services.movement_repetitions() if r["name"] == "Pull-up")
    assert pullup["repetitions"] == 12
    assert pullup["times"] == 1
    assert pullup["workouts"] == []  # belongs to no workout
    assert pullup["extra"] is True


def test_movement_repetitions_merges_extra_into_matching_movement(app, seeded):
    """An extra with the name of a real movement adds to that movement's total."""
    push = seeded["push"]
    services.log_session(
        push.id,
        date(2026, 9, 5),
        45,
        {m.id: 10 for m in push.movements},
        "good",
        extra_movements=[("Lunge", 7)],  # part of Leg day, not of Push day
    )
    lunge = next(r for r in services.movement_repetitions() if r["name"] == "Lunge")
    assert lunge["repetitions"] == 47  # 20 + 20 from Leg day, plus the extra 7
    assert lunge["times"] == 3
    assert lunge["workouts"] == ["Leg day"]
    assert lunge["extra"] is True


def test_movement_repetitions_extra_counts_towards_the_grand_total(app, seeded):
    legs = seeded["legs"]
    before = sum(r["repetitions"] for r in services.movement_repetitions())
    services.log_session(
        legs.id,
        date(2026, 9, 5),
        45,
        {m.id: 10 for m in legs.movements},
        "good",
        extra_movements=[("Pull-up", 12)],
    )
    after = sum(r["repetitions"] for r in services.movement_repetitions())
    assert after == before + 10 + 10 + 12


# ------------------------------------------ movement_repetitions: the heatmap


def cells(row):
    """Flatten a movement's heatmap into {iso date: cell}, dropping padding."""
    return {
        cell["date"]: cell
        for week in row["heatmap"]["weeks"]
        for cell in week
        if cell
    }


def test_movement_heatmap_counts_repetitions_per_day(app, seeded):
    squat = next(
        r for r in services.movement_repetitions(end=date(2026, 9, 8))
        if r["name"] == "Squat"
    )
    by_date = cells(squat)
    assert by_date["2026-09-01"]["count"] == 30
    assert by_date["2026-09-03"]["count"] == 35  # 30 in Leg day + 5 in Push day
    assert by_date["2026-09-02"]["count"] == 0
    assert squat["heatmap"]["max"] == 35


def test_movement_heatmap_spans_the_whole_window_monday_first(app, seeded):
    end = date(2026, 9, 8)
    row = services.movement_repetitions(end=end)[0]
    assert len(cells(row)) == services.MOVEMENT_HEATMAP_DAYS
    assert all(len(week) == 7 for week in row["heatmap"]["weeks"])
    first_full_week = next(w for w in row["heatmap"]["weeks"] if all(w))
    assert date.fromisoformat(first_full_week[0]["date"]).weekday() == 0
    assert max(cells(row)) == end.isoformat()


def test_movement_heatmap_levels_are_relative_to_that_movements_best_day(app, seeded):
    rows = {
        r["name"]: r for r in services.movement_repetitions(end=date(2026, 9, 8))
    }
    # Squat's best day is 35 and Bench press's is 10, but each tops out at 4.
    assert cells(rows["Squat"])["2026-09-03"]["level"] == 4
    assert cells(rows["Bench press"])["2026-09-03"]["level"] == 4
    assert cells(rows["Squat"])["2026-09-02"]["level"] == 0


def test_movement_heatmap_sums_repetitions_done_twice_on_one_date(app):
    legs = services.create_workout("Leg day", ["Squat"])
    push = services.create_workout("Push day", ["Bench press"])
    services.log_session(legs.id, date(2026, 9, 3), 45, {legs.movements[0].id: 25}, "good")
    # Squat again the same day, as an extra of another workout's session.
    services.log_session(
        push.id,
        date(2026, 9, 3),
        30,
        {push.movements[0].id: 10},
        "bad",
        extra_movements=[("Squat", 7)],
    )
    squat = next(
        r for r in services.movement_repetitions(end=date(2026, 9, 8))
        if r["name"] == "Squat"
    )
    assert cells(squat)["2026-09-03"]["count"] == 32
    assert squat["heatmap"]["max"] == 32


def test_movement_heatmap_includes_extra_only_movements(app, seeded):
    legs = seeded["legs"]
    services.log_session(
        legs.id,
        date(2026, 9, 6),
        45,
        {m.id: 10 for m in legs.movements},
        "good",
        extra_movements=[("Pull-up", 12)],
    )
    pullup = next(
        r for r in services.movement_repetitions(end=date(2026, 9, 8))
        if r["name"] == "Pull-up"
    )
    assert cells(pullup)["2026-09-06"]["count"] == 12
    assert pullup["heatmap"]["max"] == 12


def test_movement_heatmap_ignores_dates_outside_the_window(app, seeded):
    """Older sessions still count towards the total, but not towards the grid."""
    squat = next(
        r for r in services.movement_repetitions(end=date(2028, 1, 1))
        if r["name"] == "Squat"
    )
    assert squat["repetitions"] == 65  # all-time total is unchanged
    assert squat["heatmap"]["max"] == 0  # nothing inside the last 365 days
    assert all(cell["count"] == 0 for cell in cells(squat).values())


def test_movement_heatmap_has_the_same_month_axis(app, seeded):
    row = services.movement_repetitions(end=date(2026, 9, 8))[0]
    months = row["heatmap"]["months"]
    assert [m["label"] for m in months][:2] == ["Sep 2025", "Oct 2025"]
    assert sum(m["weeks"] for m in months) == len(row["heatmap"]["weeks"])


def test_movement_never_performed_has_no_heatmap(app):
    services.create_workout("Core day", ["Plank"])
    assert services.movement_repetitions()[0]["heatmap"] is None


# ------------------------------------ movement_repetitions: the repetition trend


@pytest.fixture()
def weekly(app):
    """One workout logged weekly for 10 weeks, with three shapes of history."""
    workout = services.create_workout("Test", ["Rising", "Falling", "Steady"])
    ids = {m.name: m.id for m in workout.movements}
    start = date(2026, 6, 1)
    for week in range(10):
        services.log_session(
            workout.id,
            start + timedelta(weeks=week),
            45,
            {
                ids["Rising"]: 5 + week * 3,
                ids["Falling"]: 40 - week * 3,
                ids["Steady"]: 20 + (week % 2),
            },
            "good",
        )
    return workout


def trend_of(name, end=date(2026, 8, 15)):
    return next(
        r for r in services.movement_repetitions(end=end) if r["name"] == name
    )["trend"]


def test_trend_detects_rising_repetitions(app, weekly):
    trend = trend_of("Rising")
    assert trend["direction"] == "up"
    assert trend["late"] > trend["early"]
    assert trend["change"] > services.REPETITION_TREND_TOLERANCE


def test_trend_detects_falling_repetitions(app, weekly):
    trend = trend_of("Falling")
    assert trend["direction"] == "down"
    assert trend["late"] < trend["early"]
    assert trend["change"] < -services.REPETITION_TREND_TOLERANCE


def test_trend_calls_small_changes_similar(app, weekly):
    trend = trend_of("Steady")
    assert trend["direction"] == "similar"
    assert abs(trend["change"]) <= services.REPETITION_TREND_TOLERANCE


def test_trend_halves_account_for_every_repetition(app, weekly):
    for row in services.movement_repetitions(end=date(2026, 8, 15)):
        assert row["trend"]["early"] + row["trend"]["late"] == row["repetitions"]


def test_trend_change_is_the_fraction_the_later_half_differs_by(app):
    workout = services.create_workout("Leg day", ["Squat"])
    movement_id = workout.movements[0].id
    services.log_session(workout.id, date(2026, 9, 1), 45, {movement_id: 20}, "good")
    services.log_session(workout.id, date(2026, 9, 3), 45, {movement_id: 30}, "good")
    trend = trend_of("Squat", end=date(2026, 9, 8))
    assert (trend["early"], trend["late"]) == (20, 30)
    assert trend["change"] == 0.5  # +50%


@pytest.mark.parametrize(
    "tolerance_case,expected",
    [(1.15, "similar"), (1.16, "up"), (0.85, "similar"), (0.84, "down")],
)
def test_trend_tolerance_boundary(app, tolerance_case, expected):
    """±15% is still 'similar'; just past it becomes a direction."""
    workout = services.create_workout("Leg day", ["Squat"])
    movement_id = workout.movements[0].id
    services.log_session(workout.id, date(2026, 9, 1), 45, {movement_id: 100}, "good")
    services.log_session(
        workout.id, date(2026, 9, 3), 45, {movement_id: round(100 * tolerance_case)}, "good"
    )
    assert trend_of("Squat", end=date(2026, 9, 8))["direction"] == expected


def test_trend_is_unknown_for_a_single_date(app):
    workout = services.create_workout("Leg day", ["Squat"])
    services.log_session(
        workout.id, date(2026, 9, 1), 45, {workout.movements[0].id: 30}, "good"
    )
    trend = trend_of("Squat", end=date(2026, 9, 8))
    assert trend["direction"] is None
    assert trend["split"] is None


def test_trend_is_unknown_for_a_movement_never_performed(app):
    services.create_workout("Core day", ["Plank"])
    assert services.movement_repetitions()[0]["trend"]["direction"] is None


def test_trend_is_up_with_no_earlier_baseline(app):
    """Nothing in the earlier half, something in the later one: up, but no %."""
    workout = services.create_workout("Leg day", ["Squat"])
    movement_id = workout.movements[0].id
    services.log_session(workout.id, date(2026, 9, 1), 45, {movement_id: 0}, "good")
    services.log_session(workout.id, date(2026, 9, 3), 45, {movement_id: 30}, "good")
    trend = trend_of("Squat", end=date(2026, 9, 8))
    assert trend["direction"] == "up"
    assert (trend["early"], trend["late"]) == (0, 30)
    assert trend["change"] is None


def test_trend_of_extra_only_movement(app):
    workout = services.create_workout("Leg day", ["Squat"])
    for day, reps in ((date(2026, 9, 1), 5), (date(2026, 9, 5), 20)):
        services.log_session(
            workout.id, day, 45, {workout.movements[0].id: 10}, "good",
            extra_movements=[("Pull-up", reps)],
        )
    assert trend_of("Pull-up", end=date(2026, 9, 8))["direction"] == "up"


def test_trend_reads_the_whole_history_not_just_the_heatmap_window(app):
    """Sessions older than the heatmap window still shape the trend."""
    workout = services.create_workout("Leg day", ["Squat"])
    movement_id = workout.movements[0].id
    services.log_session(workout.id, date(2020, 1, 1), 45, {movement_id: 100}, "good")
    services.log_session(workout.id, date(2026, 9, 1), 45, {movement_id: 10}, "good")
    row = next(
        r for r in services.movement_repetitions(end=date(2026, 9, 8))
        if r["name"] == "Squat"
    )
    assert row["heatmap"]["max"] == 10  # only the recent session is on the grid
    assert row["trend"]["direction"] == "down"  # but the trend sees both
    assert (row["trend"]["early"], row["trend"]["late"]) == (100, 10)


# ------------------------------------------------------------- feeling_trend


def test_feeling_trend_covers_every_day_in_window(app):
    end = date(2026, 9, 8)
    trend = services.feeling_trend(end=end, days=30)
    assert len(trend["days"]) == 30
    assert trend["days"][0]["date"] == (end - timedelta(days=29)).isoformat()
    assert trend["days"][-1]["date"] == end.isoformat()
    assert trend["start"] == end - timedelta(days=29)
    assert trend["end"] == end


def test_feeling_trend_scores_and_labels(app, seeded):
    by_date = {d["date"]: d for d in services.feeling_trend(end=date(2026, 9, 8))["days"]}
    assert by_date["2026-09-01"]["sessions"] == 1
    assert by_date["2026-09-01"]["score"] == 3
    assert by_date["2026-09-01"]["feeling"] == "good"
    # 2026-09-03 has an 'okay' (2) and a 'bad' (1) session: average 1.5.
    assert by_date["2026-09-03"]["sessions"] == 2
    assert by_date["2026-09-03"]["score"] == 1.5
    assert by_date["2026-09-03"]["feeling"] == "okay"  # rounded half-up
    assert by_date["2026-09-03"]["counts"] == {"good": 0, "okay": 1, "bad": 1}


def test_feeling_trend_rest_days_have_no_score(app, seeded):
    by_date = {d["date"]: d for d in services.feeling_trend(end=date(2026, 9, 8))["days"]}
    rest = by_date["2026-09-02"]
    assert rest["sessions"] == 0
    assert rest["score"] is None
    assert rest["feeling"] is None


def test_feeling_trend_totals(app, seeded):
    trend = services.feeling_trend(end=date(2026, 9, 8))
    assert trend["totals"] == {"good": 1, "okay": 1, "bad": 1}
    assert trend["sessions"] == 3


def test_feeling_trend_excludes_sessions_outside_window(app, seeded):
    trend = services.feeling_trend(end=date(2026, 9, 8), days=3)  # 6-8 Sep only
    assert trend["sessions"] == 0
    assert all(d["score"] is None for d in trend["days"])


def test_feeling_trend_empty_db(app):
    trend = services.feeling_trend(end=date(2026, 9, 8))
    assert trend["sessions"] == 0
    assert trend["totals"] == {"good": 0, "okay": 0, "bad": 0}
    assert len(trend["days"]) == services.TREND_DAYS
