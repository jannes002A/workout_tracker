# Training Log

A small Flask app for keeping a workout diary: define your workouts, log each
session movement by movement, and see what the numbers say.

It's a single-user local app — no accounts, no login. Data lives in a SQLite
file on your machine.

## Requirements

Python 3.14 or newer.

## Setup

With [uv](https://docs.astral.sh/uv/):

    uv sync

Or with pip:

    pip install -r requirements.txt

## Run

    python main.py

Then open <http://127.0.0.1:5000>. The SQLite database is created automatically
at `instance/workouts.db` on first start, so there's nothing to migrate or seed.
Delete that file to start over.

The dev server runs with `debug=True`, which enables the reloader and the
in-browser debugger. Don't expose it beyond localhost.

## Pages

### Create — `/create`

Name a workout and list the movements it consists of ("Leg day": back squat,
lunges). Add as many movement fields as you need. Workout names must be unique,
and a workout needs at least one movement. Existing workouts and their movements
are listed underneath.

Under the movement fields, every movement already in your log is offered as a
button — the movements of your other workouts as well as any extra movement you
logged on the track page. Selecting one fills it into the form, so you don't
retype it. Selecting the same movement twice does nothing, and a duplicate is
dropped when the workout is saved either way.

### Track — `/track`

Log a session you've done:

| Field | Values |
| --- | --- |
| Workout | any workout you've created |
| Date | today or any of the previous 30 days |
| Length | 10–90 minutes, in 5-minute steps |
| Repetitions | 0–120, **entered separately for every movement of the workout** (0 = part of the session but not done) |
| Feeling | good, okay or bad |
| Extra movements | any number of one-off movements with their own repetitions |

Choosing a workout reveals its movements, each with its own repetition
dropdown, so the session records what you actually did per exercise rather
than a single lump total.

Did something that isn't part of the workout? **Add another movement** under
"Extra movements" records it with its repetitions for this session only. It
counts towards your analytics like any other movement, but it is *not* added to
the workout, so the next session won't ask you for it. An extra can't repeat a
movement the workout already has — set that movement's repetitions instead.

### Analytics — `/analytics`

Four sections, top to bottom:

1. **Activity, last 12 months** — a GitHub-style heatmap with one cell per day,
   shaded by how many sessions you logged that day relative to your busiest day.
   Month and year labels run along the top of every heatmap on the page.
2. **Workouts performed** — the total number of workouts you've done, then a
   table of how many times each workout has been done and how those sessions
   felt, broken into Good / Okay / Bad columns. Most frequent first; workouts
   you've never tracked appear with a count of 0.
3. **How it felt, last 30 days** — a bar chart with one bar per day, coloured
   and scaled by how the workout felt (good is tallest). Days without a workout
   show a flat marker, so rest days stay visible as rest rather than as missing
   data. If you logged more than one session on a day, the bar shows the average.
4. **Repetitions per movement** — your total repetitions, then a heatmap per
   movement: one cell per day of the last 12 months, shaded by how many
   repetitions you did of that movement that day. Each movement is shaded
   against its own busiest day, so a light cell for one movement and a light
   cell for another don't mean the same number — the caption gives each
   movement's best day. Movements are grouped by name, so one that appears in
   several workouts gets a single heatmap with its days combined; extra
   movements appear here too, marked "extra, this session only".

   Each movement carries a trend badge — **↑ going up**, **↓ going down** or
   **→ holding steady** — comparing the first half of that movement's history
   with the second half, with the percentage change where there is an earlier
   baseline to compare against. A change within 15% either way counts as
   holding steady. Hover the badge for both half-totals and the split date. A
   movement performed on only one date gets no badge, since there is nothing to
   compare.

## How it's put together

    main.py             entry point: create_app() + app.run(debug=True)
    src/__init__.py     application factory, config, db.create_all()
    src/models.py       SQLAlchemy models
    src/routes.py       the three pages, as one blueprint
    src/services.py     all business logic, validation and analytics
    src/templates/      Jinja templates
    src/static/         stylesheet
    tests/              pytest suite

Route handlers only read the request and render a response; every rule about
what counts as valid input, and every analytics query, lives in
`src/services.py` and raises `ValidationError` on bad input. That keeps the
logic testable without going through HTTP.

### Data model

- **Workout** — a template, e.g. "Leg day".
- **Movement** — one exercise belonging to a workout.
- **WorkoutSession** — one performed instance of a workout: date, length, feeling.
- **SessionMovement** — the repetitions done for one movement within one session.
  It either points at a `Movement` of the workout, or carries its own
  `extra_name` for a movement done in that session only.

Repetitions hang off `SessionMovement`, not off the session, which is what makes
the per-movement analytics possible. Deleting a workout cascades to its
movements, sessions and logged repetitions.

There are no migrations: `create_app` calls `db.create_all()`, which creates
missing tables but never alters existing ones. If you change a model you have to
rebuild the affected table by hand — copy the existing rows out, let
`create_all()` recreate it, and insert them back with a value for any new
column. `instance/workouts.db` holds your real training log, so back it up
first.

## Tests

    pytest

or equivalently `python -m pytest`. To run a single test or filter by name:

    pytest tests/test_services.py::test_log_session_valid
    pytest -k feeling_trend

`tests/test_services.py` and `tests/test_analytics.py` call the service
functions directly against an in-memory database; `tests/test_routes.py` drives
the pages through Flask's test client.
