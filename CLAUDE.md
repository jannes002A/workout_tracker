# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

"Training Log" — a small Flask + SQLite app to create workouts, log sessions movement by movement, and view analytics. Requires Python >= 3.14.

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

`src/models.py`: `Workout` → `Movement` (the template's exercises) and `Workout` → `WorkoutSession` (performed instances). Repetitions are **per movement, not per session**: `SessionMovement` carries a repetition count for one movement within one session, and `WorkoutSession.total_repetitions` sums them. Every relationship cascades `all, delete-orphan`, so deleting a workout clears its movements, sessions and logs.

A `SessionMovement` is one of two things, which `is_extra` distinguishes and the `name` property papers over:

- `movement_id` set — a movement of the workout template.
- `movement_id` NULL and `extra_name` set — an **extra movement**, done in that session only. It is logged and analysed like any other movement but deliberately creates no `Movement` row, so it never joins the workout and is not asked for again next session.

Allowed enum-like values live next to what they constrain: `FEELINGS` and `FEELING_SCORES` (bad=1, okay=2, good=3, used to plot the trend) in `models.py`; `DURATION_CHOICES` (10–90 in steps of 5) and `REPETITION_CHOICES` (0–120, where 0 records a movement that was part of the session but not done) in `services.py`. Routes pass these same lists to the templates to populate the dropdowns, so the form options and the server-side validation can never drift apart; the out-of-range message is built from the ends of `REPETITION_CHOICES` for the same reason.

### Create page

Besides the free-text movement fields, `/create` lists every movement name already in the
log as a chip, from `known_movement_names()` — the movements of existing workouts *and*
extras logged on the track page, deduplicated and sorted case-insensitively. A chip carries
its name in `data-movement` and a single delegated click handler fills the first empty
movement field (or appends one), skipping names already on the form; `data-*` rather than
an inline `onclick` argument is what keeps names like `Farmer's carry` from breaking the
markup. The chips need JS, so `create_workout` also drops duplicate names
case-insensitively server-side.

### Track page

`/track` renders a `reps-<movement id>` dropdown for the movements of **every** workout, in one form. A small inline script hides and `disabled`s the fieldsets of the workouts that aren't selected, so only the relevant fields are submitted. Without JS all fields are submitted, so `log_session` deliberately ignores movement ids that don't belong to the chosen workout while requiring one entry for every movement that does.

Below that sits the extra-movements fieldset: repeatable `extra-name` / `extra-reps` pairs, positionally zipped, for movements done only in this session. One empty row is rendered server-side (so it works without JS) and `addExtraMovement()` clones the `#extra-row-template` for more. Blank rows are dropped, and `log_session` rejects an extra whose name is already a movement of the workout, or repeated twice, so nothing gets double counted.

`_repetitions_from_form` and `_extra_movements_from_form` in `routes.py` do the field parsing; `REPS_FIELD_PREFIX`, `EXTRA_NAME_FIELD` and `EXTRA_REPS_FIELD` are the single source of the field-name conventions.

### Analytics page

Four sections, in this order (a test asserts the order):

1. `activity_map()` — heatmap of the last 365 days, one cell per day counting sessions.
2. `workout_frequency()` — sessions per workout, most frequent first, including workouts never performed. Each row also carries `feelings`, a count per value of `FEELINGS`, rendered as Good/Okay/Bad columns; the total session count above the table is just `frequency | sum(attribute='count')` in the template, not a service call.
3. `feeling_trend()` — one entry per day for the last `TREND_DAYS` (30) days, oldest first; rest days have `sessions` 0 and `score`/`feeling` `None`, and a day with several sessions gets their average score with the label rounded half-up.
4. `movement_repetitions()` — one entry per movement, grouped **by movement name**, so a movement appearing in several workouts (or logged as an extra) is reported once. Alongside the totals (`repetitions`, `times`, `workouts`, `extra`) each row carries `heatmap`: its own calendar grid of the last `MOVEMENT_HEATMAP_DAYS` (365) days, counting repetitions per day and summing them when a movement landed twice on one date (possible across two sessions). `heatmap` is `None` for a movement never performed, which the template renders as "Not performed yet" with no grid. The function merges five queries in Python: workout membership, linked totals, extra totals, linked per-date, extra per-date.

Both heatmaps come from **`_calendar_weeks(counts, end, days)`**, which buckets a `{date: count}` mapping into Monday-first weeks of `{"date", "count", "level"}` cells (`None` pads the first partial week), plus the window's `max` and `months` — one `{"label": "Sep 2025", "weeks": n}` per run of week columns, which the template lays out as the x axis above the grid. A week is attributed to the month of its first day, and the spans always sum to the number of columns.

Month-label alignment is CSS, not magic numbers: `--cell` and `--cell-gap` define the grid, and each label's width is `calc(var(--weeks) * (var(--cell) + var(--cell-gap)) - var(--cell-gap))` with `--weeks` set inline. Change the cell size and the axis follows. Labels are deliberately not clipped — a full month is wide enough for "May 2026" at the current font size, and only the trailing partial month is narrow, with nothing after it to overlap. Levels are 0-4 relative to that grid's own busiest day, so a movement's shading is relative to its own best day, not to other movements. Counts outside the window are ignored, so an all-time total can be non-zero while its grid is empty. The `heatmap` Jinja macro in `analytics.html` renders any of these grids, with the `unit` argument naming what a cell counts ("session" or "repetition").

`activity_map`, `feeling_trend` and the movement grids render straight into the template's markup and SVG geometry, computed in Jinja, so changing a returned shape means changing `analytics.html` too. Analytics service functions take an explicit `end` date defaulting to today, which is what lets the tests seed fixed dates.

## Tests

`tests/conftest.py` provides `app` (in-memory DB, pushed app context, dropped after each test) and `client` fixtures. `test_services.py` and `test_analytics.py` call service functions directly; `test_routes.py` exercises the HTTP layer via `client` and builds POST bodies with its `track_form` helper. Every service function is expected to have test coverage.

## Entry point

`main.py` holds `create_app()` plus `app.run(debug=True)`. (An earlier `run.py` did this
and is gone; don't reintroduce it.)
