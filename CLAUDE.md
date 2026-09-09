# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

"Training Log" — a small Flask + SQLite app to create users and workouts, log sessions movement by movement, and view analytics per user or across everyone. Requires Python >= 3.14.

## Commands

Dependencies are declared in both `pyproject.toml` (with `uv.lock`) and `requirements.txt`; keep them in sync when adding a dependency.

```bash
uv sync                       # install (or: pip install -r requirements.txt)
python main.py                # dev server with debug=True on http://127.0.0.1:5000
pytest                        # all tests
pytest tests/test_services.py::test_log_session_valid             # single test
pytest -k feeling_trend                                           # by name
```

There are no migrations — `create_app` just calls `db.create_all()`, which creates missing
tables but never alters existing ones. After a model change, drop the affected table (or
delete `instance/workouts.db` to reset all data) or the old columns will linger and inserts
will fail.

## Architecture

Application factory pattern: `create_app(test_config)` in `src/__init__.py` builds the app, initialises `db`, calls `db.create_all()`, and registers the single blueprint `main` from `src/routes.py`. Tests pass `test_config` to swap in an in-memory SQLite database.

The key structural rule is the **routes/services split**:

- `src/services.py` holds *all* business logic and validation, operating on models and dates — no Flask request/response objects. Invalid input raises `ValidationError` (a `ValueError` subclass).
- `src/routes.py` only parses `request.form`, calls a service function, and turns `ValidationError` into a `flash(..., "error")` plus a redirect or re-render. Add new logic to `services.py`, not to a route handler, so it can be tested without HTTP.

### Data model

`src/models.py`: `User` → `WorkoutSession`, `Workout` → `Movement` (the template's exercises) and `Workout` → `WorkoutSession` (performed instances). Repetitions are **per movement, not per session**: `SessionMovement` carries a repetition count for one movement within one session, and `WorkoutSession.total_repetitions` sums them. Every relationship cascades `all, delete-orphan`, so deleting a workout clears its movements, sessions and logs.

A `SessionMovement` is one of two things, which `is_extra` distinguishes and the `name` property papers over:

- `movement_id` set — a movement of the workout template.
- `movement_id` NULL and `extra_name` set — an **extra movement**, done in that session only. It is logged and analysed like any other movement but deliberately creates no `Movement` row, so it never joins the workout and is not asked for again next session.

Allowed enum-like values live next to what they constrain: `FEELINGS` and `FEELING_SCORES` (bad=1, okay=2, good=3, used to plot the trend) in `models.py`; `DURATION_CHOICES` (10–90 in steps of 5), `REPETITION_CHOICES` (0–120, where 0 records a movement that was part of the session but not done) `MIN_AGE`/`MAX_AGE` (1–120) and `MAX_COMMENT_LENGTH` (2000, the textarea's `maxlength` as well as the check) in `services.py`. Routes pass these same lists to the templates to populate the dropdowns, so the form options and the server-side validation can never drift apart; the out-of-range message is built from the ends of `REPETITION_CHOICES` for the same reason.

### Users page

`/users` creates the people whose sessions are tracked — a name (unique, compared
case-insensitively) and an age — and lists everyone with their session count and a link
straight to their filtered analytics. Age is a `type="number"` input whose `min`/`max` come
from `MIN_AGE`/`MAX_AGE`, the same constants `create_user` validates against and builds its
error message from, so the field and the check cannot drift. `_age_from_form` in
`routes.py` turns an unparseable age into `0`, which fails that same range check, so a
hand-crafted POST gets the range message rather than an `int()` traceback.

### Create page

Besides the free-text movement fields, `/create` lists every movement name already in the
log as a chip, from `known_movement_names()` — the movements of existing workouts *and*
extras logged on the track page, deduplicated and sorted case-insensitively. A chip carries
its name in `data-movement` and a single delegated click handler fills the first empty
movement field (or appends one), skipping names already on the form; `data-*` rather than
an inline `onclick` argument is what keeps names like `Farmer's carry` from breaking the
markup. The chips need JS, so `create_workout` also drops duplicate names
case-insensitively server-side.

**Workouts are shared; sessions belong to a user.** A `Workout` is a template anyone can
perform, so `/create` is not per-user and `known_movement_names()` spans everybody. What is
per-user is the `WorkoutSession`: `user_id` is `nullable=False`, so every session is logged
against a person, and deleting a user cascades away their sessions and logs while leaving
the workout templates alone.

### Track page

`/track` opens with a `user_id` dropdown naming who trained — sessions cannot exist without
one, so the page renders "You need a user first" (and no form at all) until a user exists,
the same way it already did for workouts. `USER_FIELD` in `routes.py` is the single source
of that field name, shared with the analytics filter.

Below it, `/track` renders a `reps-<movement id>` dropdown for the movements of **every** workout, in one form. A small inline script hides and `disabled`s the fieldsets of the workouts that aren't selected, so only the relevant fields are submitted. Without JS all fields are submitted, so `log_session` deliberately ignores movement ids that don't belong to the chosen workout while requiring one entry for every movement that does.

Below that sits the extra-movements fieldset: repeatable `extra-name` / `extra-reps` pairs, positionally zipped, for movements done only in this session. One empty row is rendered server-side (so it works without JS) and `addExtraMovement()` clones the `#extra-row-template` for more. Blank rows are dropped, and `log_session` rejects an extra whose name is already a movement of the workout, or repeated twice, so nothing gets double counted.

Last on the form is an optional free-text `comment` about the session. `log_session`
strips it and stores a blank one as **NULL, not `""`**, which is what lets
`session_comments` select the sessions that actually have something to say.

`_repetitions_from_form` and `_extra_movements_from_form` in `routes.py` do the field parsing; `REPS_FIELD_PREFIX`, `EXTRA_NAME_FIELD`, `EXTRA_REPS_FIELD`, `USER_FIELD` and `COMMENT_FIELD` are the single source of the field-name conventions.

### Analytics page

A `user_id` dropdown at the top reloads the page as `/analytics?user_id=N` (a plain GET
form with a submit button, so it works without JS; `onchange` just submits it early), and
every section below is then computed for that user alone. No `user_id`, a blank one, or an
id that no longer exists all fall back to "All users" — `_selected_user_id` in `routes.py`
returns `None` and `services.get_user` returns `None` for an unknown id.

Each analytics service takes `user_id: int | None = None`, and `_for_user(query, user_id)`
applies the filter (before grouping, so it lands in the WHERE clause) or leaves the query
alone for `None`. `movement_repetitions` joins `WorkoutSession` in its totals queries — a
join it does not otherwise need — purely so those totals can be filtered too.

Picking a user narrows *what is listed*, not just the counts. Across everyone the two
tables double as a list of what exists, so rows at zero belong there; on one person's page
they are noise:

- `workout_frequency` lists only the workouts the selected user has performed — an inner
  join for a `user_id`, an `outerjoin` for everyone.
- `movement_repetitions` drops any movement with `times` 0, which is exactly the set that
  would otherwise render as "Not performed yet" (`heatmap` is `None` for the same rows).
  A movement logged with 0 repetitions was still *part of* a session, so it stays.

Either section can therefore come out empty for a user who has tracked nothing, and each
renders its own "hasn't performed … yet" message instead of the across-everyone one.

Five sections, in this order (a test asserts the order):

1. `activity_map()` — heatmap of the last 365 days, one cell per day counting sessions.
2. `workout_frequency()` — sessions per workout, most frequent first, including workouts never performed. Each row also carries `feelings`, a count per value of `FEELINGS`, rendered as Good/Okay/Bad columns; the total session count above the table is just `frequency | sum(attribute='count')` in the template, not a service call.
3. `feeling_trend()` — one entry per day for the last `TREND_DAYS` (30) days, oldest first; rest days have `sessions` 0 and `score`/`feeling` `None`, and a day with several sessions gets their average score with the label rounded half-up.
4. `movement_repetitions()` — one entry per movement, grouped **by movement name**, so a movement appearing in several workouts (or logged as an extra) is reported once. `workouts` names where the repetitions actually **came from** — the workouts of the sessions the movement was logged in — not every workout that happens to contain a movement of that name. An extra belongs to no workout, so a movement done only as an extra lists none; otherwise doing "Squats" as an extra during Arm day would label it "Leg day" and imply a workout that was never performed. A movement nobody has performed has no sessions to go on and falls back to the workouts it belongs to, which is the only thing there is to say about it — that is what the "Not performed yet · Leg day" caption shows. Alongside the totals (`repetitions`, `times`, `workouts`, `extra`) each row carries `heatmap`: its own calendar grid of the last `MOVEMENT_HEATMAP_DAYS` (365) days, counting repetitions per day and summing them when a movement landed twice on one date (possible across two sessions). `heatmap` is `None` for a movement never performed, which the template renders as "Not performed yet" with no grid. Each row also carries `trend` from **`_repetition_trend`**: it splits the movement's own history — first performed date to last — into two equal-length halves and compares the repetitions in each, giving `direction` (`"up"`, `"down"`, `"similar"` or `None`), both half totals, the `split` date and `change` as a fraction. Within ±`REPETITION_TREND_TOLERANCE` (15%) counts as `"similar"`; `direction` is `None` when everything falls on one date, and `change` is `None` when the earlier half is 0 (no baseline to be a percentage of), which the badge renders as a direction with no percentage. The trend reads the whole history, not just the heatmap window, so an old session can shape a trend whose grid looks empty. The function merges five queries in Python: workout membership, linked totals, extra totals, linked per-date, extra per-date.

5. `session_comments()` — the sessions carrying a free-text note, **most recent first**
   (same-day sessions newest-logged first, for which the session id stands in). One entry
   per comment: `date` (a `date`, formatted in the template), `workout`, `feeling`, `user`
   and `comment`. Sessions with no comment are left out, so this is a log of what was
   written, not of what was tracked. `user` is always carried but the template prints it
   only in the across-everyone view — with a user selected the page already says whose it
   is. The text renders with `white-space: pre-wrap`, so line breaks typed on the track
   page survive.

Both heatmaps come from **`_calendar_weeks(counts, end, days)`**, which buckets a `{date: count}` mapping into Monday-first weeks of `{"date", "count", "level"}` cells (`None` pads the first partial week), plus the window's `max` and `months` — one `{"label": "Sep 2025", "weeks": n}` per run of week columns, which the template lays out as the x axis above the grid. A week is attributed to the month of its first day, and the spans always sum to the number of columns.

Month-label alignment is CSS, not magic numbers: `--cell` and `--cell-gap` define the grid, and each label's width is `calc(var(--weeks) * (var(--cell) + var(--cell-gap)) - var(--cell-gap))` with `--weeks` set inline. Change the cell size and the axis follows. Labels are deliberately not clipped — a full month is wide enough for "May 2026" at the current font size, and only the trailing partial month is narrow, with nothing after it to overlap. Levels are 0-4 relative to that grid's own busiest day, so a movement's shading is relative to its own best day, not to other movements. Counts outside the window are ignored, so an all-time total can be non-zero while its grid is empty. The `heatmap` Jinja macro in `analytics.html` renders any of these grids, with the `unit` argument naming what a cell counts ("session" or "repetition").

`activity_map`, `feeling_trend` and the movement grids render straight into the template's markup and SVG geometry, computed in Jinja, so changing a returned shape means changing `analytics.html` too. Analytics service functions take an explicit `end` date defaulting to today, which is what lets the tests seed fixed dates.

## Tests

`tests/conftest.py` provides `app` (in-memory DB, pushed app context, dropped after each
test), `client`, and the `user` / `other_user` fixtures ("Alex", 34 and "Sam", 41). Since
`log_session` requires a user, almost every test takes `user`; `test_analytics.py`'s
`two_users` fixture splits one shared workout across both people so the per-user analytics
can be checked against a clean split. `test_services.py` and `test_analytics.py` call service functions directly; `test_routes.py` exercises the HTTP layer via `client` and builds POST bodies with its `track_form` helper. Every service function is expected to have test coverage.

## Entry point

`main.py` holds `create_app()` plus `app.run(debug=True)`. (An earlier `run.py` did this
and is gone; don't reintroduce it.)
