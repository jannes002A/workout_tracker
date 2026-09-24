# Training Log

A small Flask app for keeping a workout diary: add the people who train, define
the workouts, log each session exercise by exercise, and see what the numbers
say.

It runs locally with no login — anyone opening the page can track a session for
any of the users and read everyone's numbers. "Users" are simply the people
whose sessions are being recorded, so a household or a training group can share
one log. Data lives in a SQLite file on your machine.

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
in-browser debugger. Don't expose it beyond localhost — to run the app for
real, use the container described under [Deployment](#deployment).

## Deployment

A hardened container is provided. It serves the app with gunicorn rather than
Flask's development server, runs as an unprivileged user on a read-only
filesystem, and publishes to localhost only.

    cp .env.example .env
    python -c "import secrets; print(secrets.token_hex(32))"   # paste into .env
    docker compose up -d --build

Then open <http://127.0.0.1:8000>. `docker compose logs -f` follows the log,
`docker compose down` stops it; the database lives in the named volume
`training-log_db` and survives both.

### Read this before putting it on a network

**The app has no login of any kind.** Anyone who can reach the port can read
and change everyone's data. The container makes the *process* hard to abuse; it
cannot make an unauthenticated app safe to expose. That is why compose
publishes the port as `127.0.0.1:8000:8000` — bound to the loopback interface,
not to every interface on the machine.

To reach it from elsewhere, put a reverse proxy in front that terminates TLS
and authenticates the request, and leave the app's own port on loopback. Then:

- set `SESSION_COOKIE_SECURE=1` in `.env`, so the session cookie is only ever
  sent over HTTPS (leave it `0` while serving plain HTTP, or browsers drop the
  cookie and the flash messages silently stop appearing);
- set `FORWARDED_ALLOW_IPS` to the proxy's address on the container network, so
  gunicorn trusts `X-Forwarded-For` and `X-Forwarded-Proto` from the proxy and
  from nothing else. Never set it to `*`.

### Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `SECRET_KEY` | *(none — required)* | Signs the session cookie. The container sets `APP_ENV=production`, and the app refuses to start without a key of its own |
| `SESSION_COOKIE_SECURE` | `0` | `1` marks the session cookie Secure. Turn on behind HTTPS |
| `WEB_CONCURRENCY` | `2` | Gunicorn worker processes |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Whose `X-Forwarded-*` headers gunicorn believes |
| `LOG_LEVEL` | `info` | Gunicorn log level |
| `PORT` | `8000` | Port inside the container |

`.env` holds the secret and is gitignored; `.env.example` is the template to
copy. `SECRET_KEY` signs the cookie the flash messages ride in, so anyone who
knows it can forge one — it belongs in `.env`, not in the source.

### What the container does about security

- **gunicorn, not `app.run(debug=True)`.** The development server's in-browser
  debugger executes arbitrary Python; it never listens on a deployed port.
- **No secret in the image.** `create_app` reads `SECRET_KEY` from the
  environment and, with `APP_ENV=production` set, refuses to start on the `dev`
  key that lives in the source for local runs.
- **Non-root.** The process runs as uid 10001 with every Linux capability
  dropped and `no-new-privileges`, so no setuid binary can raise it back.
- **Read-only root filesystem.** The only writable paths are the database
  volume and a `noexec` tmpfs at `/tmp`, so nothing can drop a file somewhere
  it would later be executed from.
- **A small image.** Two stages: uv installs the locked dependencies in the
  first, and only the virtualenv and the source cross into the second. The
  shipped image has no uv, no compiler, no `curl`, and no test suite.
- **Reproducible, verified dependencies.** `uv sync --frozen` builds strictly
  from `uv.lock`, hash-checking every package and failing if the lock has
  drifted from `pyproject.toml`. Both base images are pinned by digest.
- **Nothing extra copied in.** `.dockerignore` keeps `instance/` out, so a
  local database full of real training data can never be baked into an image.
- **Bounded.** Memory, CPU, process count and log size are all capped, and a
  healthcheck fetches a page that queries the database rather than just opening
  a socket.

## Pages

### Users — `/users`

Add the people whose sessions are tracked: a name (unique, compared
case-insensitively) and an age between 1 and 120. Everyone added is listed
underneath with their age, how many sessions they have logged and a link
straight to their own analytics.

Sessions can't exist without a user, so this is the page to start on. Workouts
are *not* per user — they are shared templates anyone can perform. Deleting a
user takes their sessions and logged repetitions with them and leaves the
workout templates alone.

### Create — `/create`

Name a workout and list the exercises it consists of ("Leg day": back squat,
lunges). Add as many exercise fields as you need. Workout names must be unique,
and a workout needs at least one exercise. Existing workouts and their exercises
are listed underneath.

Under the exercise fields, every exercise already in the log is offered as a
button — the exercises of the other workouts as well as any extra exercise
logged on the track page. Selecting one fills it into the form, so you don't
retype it. Selecting the same exercise twice does nothing, and a duplicate is
dropped when the workout is saved either way.

### Track — `/track`

Log a session someone has done:

| Field | Values |
| --- | --- |
| Who did it | any user you've added — the session is logged against them |
| Workout | any workout you've created |
| Date | today or any of the previous 30 days |
| Length | 10–90 minutes, in 5-minute steps |
| How repetitions are counted | a total per exercise, or sets × repetitions per set |
| Sets | 1–20, per exercise, asked for only when counting in sets |
| Repetitions | 0–120, **entered separately for every exercise of the workout** (0 = part of the session but not done) — the total when counting totals, the repetitions of one set when counting in sets |
| Extra kg | **none** or 1–200, also per exercise — the extra weight carried for those repetitions. It opens on *none*: leave it there for a bodyweight exercise and it is counted in repetitions only, with no weight moved |
| Feeling | good, okay or bad |
| Extra exercises | any number of one-off exercises with their own sets, repetitions and weight |
| Comment | an optional free-text note about the session, up to 2000 characters |

The page asks for the user first, and says so instead of showing a form when
there is no user yet — the same way it already did for workouts.

Choosing a workout reveals its exercises, each with its own repetition and
weight dropdown, so the session records what was actually done per exercise
rather than a single lump total.

The dropdown at the top of the form decides how those repetitions are counted.
**Total repetitions per exercise** is the default and asks for one figure per
exercise. **Sets × repetitions per set** adds a sets column: give each exercise
its number of sets and the repetitions of one of them, and the two are multiplied
into what is logged — 4 sets of 10 squats is 40 repetitions. The sets are per
exercise, so squats can be 4×10 in the same session lunges are 3×12, and the
analytics read the multiplied figure, so both ways of counting land in the same
totals. The weight dropdown starts at **none** — pick a
number only when you actually carried something. An exercise left at *none* still
counts every repetition; it simply has no weight to report, and never shows up as
0 kg moved.

Did something that isn't part of the workout? **Add another exercise** under
"Extra exercises" records it with its sets, repetitions and weight for this
session only. It counts towards the analytics like any other exercise, but it is *not*
added to the workout, so the next session won't ask for it. An extra can't
repeat an exercise the workout already has — set that exercise's repetitions
instead — and can't be listed twice in one session.

The comment is kept as written, line breaks included, and shows up on the
analytics page. Leaving it blank records no note at all rather than an empty
one.

### Analytics — `/analytics`

Two dropdowns at the top pick whose numbers to show and for which sort of
sport. "All users" and "All sports" are the defaults and cover everything;
picking a person reloads the page as `/analytics?user_id=N`, picking a sport as
`/analytics?category=judo`, and the two combine, narrowing every section below
to that person's sessions of that sport. A session counts as the sport its
workout was when it was logged, so re-labelling a workout later doesn't move its
past sessions to another sport. It's a plain GET form with a submit button, so
it works without JavaScript, and clicking a day on the map keeps both filters.

Picking a user or a sport narrows *what is listed*, not just the counts. Across
everyone the workout and exercise tables double as a list of what exists, so
entries nobody has performed belong there; on a filtered page they'd be noise, so
workouts they've never done and exercises they've never performed are left out
entirely. Either section can therefore come out empty for someone who has
tracked nothing.

Five sections, top to bottom:

1. **Activity, last 12 months** — a GitHub-style heatmap with one cell per day,
   shaded by how many sessions were logged that day relative to the busiest day.
   Month and year labels run along the top of every heatmap on the page.
2. **Workouts performed** — the total number of sessions, then a table of how
   many times each workout has been done and how those sessions felt, broken
   into Good / Okay / Bad columns. Most frequent first; across everyone,
   workouts nobody has tracked appear with a count of 0.
3. **How it felt, last 30 days** — a bar chart with one bar per day, coloured
   and scaled by how the workout felt (good is tallest). Days without a workout
   show a flat marker, so rest days stay visible as rest rather than as missing
   data. If more than one session was logged on a day, the bar shows the average.
4. **Repetitions per exercise** — the total repetitions and total weight
   moved, then a heatmap per exercise: one cell per day of the last 12 months,
   shaded by how many repetitions of that exercise were done that day. Each
   exercise is shaded against its own busiest day, so a light cell for one
   exercise and a light cell for another don't mean the same number — the
   caption gives each exercise's best day. Exercises are grouped by name, so one
   that appears in several workouts gets a single heatmap with its days
   combined; extra exercises appear here too, marked "extra, this session only".

   The workouts named in a caption are where the repetitions actually came
   from — the workouts of the sessions the exercise was logged in — so doing
   "Squats" as an extra during Arm day doesn't label it "Leg day". An exercise
   done only as an extra names no workout at all, and one nobody has performed
   falls back to the workouts it belongs to, which is all there is to say about
   it.

   Where you carried something, each caption also gives the **weight moved** for
   that exercise — the extra weight of each set counted once per repetition of
   it, so 10 reps at 40 kg counts the same as 20 reps at 20 kg — and the **best
   session**, the single session that accounts for most of it, with its date.
   Both cover the whole history rather than just the 12 months in the grid, so a
   best session can be older than the heatmap below it.

   Only sets done *with* extra weight count towards any of that. An exercise you
   have only ever done at bodyweight is reported in repetitions alone — no weight
   clause, no best session, and no 0 kg — and if nothing on the page was ever
   carried, the "kg moved in total" figure drops out too. Repetitions are counted
   the same either way: an exercise done weighted one session and at bodyweight
   the next is a single row totalling both, with only its weight limited to the
   sets that carried something.

   Each exercise carries a trend badge — **↑ going up**, **↓ going down** or
   **→ holding steady** — comparing the repetitions of the last two sessions
   that exercise was logged in, with the absolute difference in repetitions
   (e.g. "+10 reps"). Only an identical count is holding steady. Hover the
   badge for both sessions' repetitions and dates. An exercise logged in only
   one session gets no badge, since there is nothing to compare.
5. **Session comments** — the last 5 notes written on the track page, most
   recent first, each with its date, workout, how it felt and (in the
   across-everyone view) who wrote it. Sessions without a note are left out, so
   this is a log of what was written rather than of what was tracked — and it's
   the one section that doesn't list everything it knows about.

## How it's put together

    main.py             entry point: create_app() + app.run(debug=True)
    src/__init__.py     application factory, config, db.create_all()
    src/models.py       SQLAlchemy models
    src/routes.py       the four pages, as one blueprint
    src/services.py     all business logic, validation and analytics
    src/templates/      Jinja templates
    src/static/         stylesheet
    tests/              pytest suite

Route handlers only read the request and render a response; every rule about
what counts as valid input, and every analytics query, lives in
`src/services.py` and raises `ValidationError` on bad input. That keeps the
logic testable without going through HTTP.

The dropdown choices are defined once in `src/services.py` and passed to the
templates, so the options a form offers and the values the server accepts can't
drift apart.

### Data model

- **User** — a person whose sessions are tracked: a name and an age.
- **Workout** — a template, e.g. "Leg day", shared by everyone.
- **Exercise** — one exercise belonging to a workout, e.g. "Squat".
- **WorkoutSession** — one performed instance of a workout, by one user: date,
  length, feeling and an optional comment.
- **SessionExercise** — the repetitions done for one exercise within one session,
  and the extra weight carried for them, which is empty when there was none. It
  either points at an `Exercise` of the workout, or carries its own `extra_name`
  for an exercise done in that session only.

Repetitions and weight hang off `SessionExercise`, not off the session, which is
what makes the per-exercise analytics possible. Deleting a workout cascades to
its exercises, sessions and logged repetitions; deleting a user cascades to
their sessions and logs, but not to the shared workouts.

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
the pages through Flask's test client; `tests/test_config.py` covers the
settings `create_app` reads from the environment, including the refusal to
start in production without a `SECRET_KEY`.
