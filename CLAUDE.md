# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

"Training Log" — a small Flask + SQLite app to create users and workouts, log sessions exercise by exercise, and view analytics per user or across everyone. Requires Python >= 3.14.

## Commands

Dependencies are declared in both `pyproject.toml` (with `uv.lock`) and `requirements.txt`; keep them in sync when adding a dependency.

```bash
uv sync                       # install (or: pip install -r requirements.txt)
python main.py                # dev server with debug=True on http://127.0.0.1:5000
pytest                        # all tests
pytest tests/test_services.py::test_log_session_valid             # single test
pytest -k feeling_trend                                           # by name
docker compose up -d --build  # the deployment, gunicorn on http://127.0.0.1:8000
```

Dependencies split three ways in `pyproject.toml`: the runtime two (`flask`,
`flask-sqlalchemy`), the `deploy` **extra** (`gunicorn`, which only the
container installs) and the `dev` group (`pytest`). `requirements.txt` is the
flat list of all of them.

There are no migrations — `create_app` just calls `db.create_all()`, which creates missing
tables but never alters existing ones. After a model change, drop the affected table (or
delete `instance/workouts.db` to reset all data) or the old columns will linger and inserts
will fail. (`SessionExercise.weight` was added that way — an `instance/workouts.db`
predating it needs its `session_exercise` table dropped. It later became
`nullable=True` for the "no extra weight" option, which SQLite will not relax
in place either: a database carrying the old `weight INTEGER NOT NULL` rejects
every bodyweight log until that table is dropped or rebuilt. `SessionExercise.sets`
arrived the same way and wants the same table dropped. `WorkoutSession.category`
is the one that did *not* need it: a NOT NULL column with a constant default is
the one shape SQLite will add in place, so an older database takes
`ALTER TABLE workout_session ADD COLUMN category VARCHAR(20) NOT NULL DEFAULT
'weights'` and keeps its sessions, which is what `instance/workouts.db` was
given — `instance/workouts.db.bak-before-category` is the copy from before.
`Workout.category` is the same shape and was added the same way:
`ALTER TABLE workout ADD COLUMN category VARCHAR(40) NOT NULL DEFAULT
'weights'`, followed by an `UPDATE` giving each workout the sort of sport its
sessions had already been logged as, so the create page agrees with the
activity map — `instance/workouts.db.bak-before-workout-category` is the copy
from before. The `category` table itself needed nothing: `db.create_all()`
creates a table that isn't there, and `services.ensure_categories()` seeds it.)

## Architecture

Application factory pattern: `create_app(test_config)` in `src/__init__.py` builds the app, initialises `db`, calls `db.create_all()` and `services.ensure_categories()` (which seeds the sorts of sport), and registers the single blueprint `main` from `src/routes.py`. Tests pass `test_config` to swap in an in-memory SQLite database.

The key structural rule is the **routes/services split**:

- `src/services.py` holds *all* business logic and validation, operating on models and dates — no Flask request/response objects. Invalid input raises `ValidationError` (a `ValueError` subclass).
- `src/routes.py` only parses `request.form`, calls a service function, and turns `ValidationError` into a `flash(..., "error")` plus a redirect or re-render. Add new logic to `services.py`, not to a route handler, so it can be tested without HTTP.

### Data model

`src/models.py`: `User` → `WorkoutSession`, `Workout` → `Exercise` (what the template is made of) and `Workout` → `WorkoutSession` (performed instances), plus `Category`, the sorts of sport a workout can be. Repetitions are **per exercise, not per session**: `SessionExercise` carries a repetition count *and an extra weight* for one exercise within one session, and `WorkoutSession.total_repetitions` sums the first. Every relationship cascades `all, delete-orphan`, so deleting a workout clears its exercises, sessions and logs.

The **sort of sport** is a `Category` row — `value` (what is stored), `label`
(what is shown), `color` (what the activity map shades a day of it towards) and
`position` (the order of every dropdown and of the map's legend, and the
tie-break for a day that held two sorts). It lives in the database rather than
in a constant because the create page can add one; `DEFAULT_CATEGORIES` in
`models.py` is only what an empty table is seeded with —
weights/Weights/blue, judo/Judo/red, mobility/Mobility/violet,
other/Others/black, in that order — and `DEFAULT_CATEGORY` = `"weights"` is
what the create form's dropdown opens on. `services.ensure_categories()`, which
`create_app` calls right after `db.create_all()`, is what puts them there: it
adds only the defaults that are missing, so it is safe at every startup and
never touches a sort of sport added on the page. `category_by_value` and
`label_for_category` in `models.py` are the lookups; the latter falls back to
the bare value, which is all a category deleted after the fact leaves behind.

**`Workout.category` is where the sort of sport is chosen; `WorkoutSession.category`
is a copy of it.** The workout is the template, so it is what /create asks
about; `log_session` copies the value onto the session rather than reading it
back through the workout, so re-labelling a workout tomorrow cannot recolour
the days it was already performed on. `category_label` on either reads the
label back. The session's copy is what the activity map colours a day by, and
nothing else on the analytics page reads it.

`SessionExercise.weight` is the extra load carried for those repetitions, and is
**NULL when there was none** — a bodyweight exercise, which is what the track page
pre-selects. NULL is not a weight of 0: it means the exercise is counted in
repetitions only and is left out of every weight figure rather than being totalled
as nothing. `SessionExercise.weight_moved` (`repetitions * weight`) is `None` for
such a log, `has_weight` says whether there is one, and `WorkoutSession.total_weight`
sums `weight_moved or 0`, so a session of nothing but bodyweight exercises totals 0.
`weight_moved`, not the bare weight, is what the analytics page totals: it makes a
heavy set of few repetitions and a light set of many comparable, and it is 0 for an
exercise logged at 0 repetitions however heavy the weight picked was.
`_WEIGHT_MOVED` in `services.py` is the SQL twin of `weight_moved` — NULL for the
same rows, which `SUM()` then skips — so the Python property and the queries cannot
drift. `_WEIGHTED_LOGS` alongside it is `COUNT(weight)`, 0 for an exercise only ever
done at bodyweight, which is what the `weighted` flag on an analytics row comes from.

`SessionExercise.repetitions` is always the repetitions **actually performed**,
whichever way the track page counted them, and `sets` says how they were split
up: NULL for a session counted as a total per exercise, or the number of sets
the repetitions were done in. `_performed` in `services.py` is what multiplies
them — the repetitions given alongside a number of sets are the repetitions of
*one* set. `tracked_in_sets` and `repetitions_per_set` (an exact division, since
the total is the product) read it back. Nothing in analytics knows about sets:
they change what goes into `repetitions`, never how it is reported, which is
why counting in sets needed no query touched.

A `SessionExercise` is one of two things, which `is_extra` distinguishes and the `name` property papers over:

- `exercise_id` set — an exercise of the workout template.
- `exercise_id` NULL and `extra_name` set — an **extra exercise**, done in that session only. It is logged and analysed like any other exercise but deliberately creates no `Exercise` row, so it never joins the workout and is not asked for again next session.

Allowed enum-like values live next to what they constrain: `FEELINGS` and `FEELING_SCORES` (bad=1, okay=2, good=3, used to plot the trend) plus, for the sorts of sport, `DEFAULT_CATEGORIES`, `DEFAULT_CATEGORY`, `CATEGORY_PALETTE` (the colours handed to the ones added on the create page) and `UNKNOWN_CATEGORY_COLOR` in `models.py` — the *values* themselves being rows, not a constant, which is why routes pass `services.category_map()` (value → row, in order) to the templates instead of a dict of labels; `MAX_CATEGORY_LABEL` (40) caps a new one's name and the input's `maxlength`; `DURATION_CHOICES` (10–90 in steps of 5), `REPETITION_CHOICES` (0–120, where 0 records an exercise that was part of the session but not done), `WEIGHT_CHOICES` (1–200) with `NO_WEIGHT` (`None`, the "no extra weight" choice), `DEFAULT_WEIGHT` = `NO_WEIGHT` and `WEIGHT_UNIT` ("kg", only ever displayed — nothing converts between units), `SET_CHOICES` (1–20) with `NO_SETS` (`None`, "these repetitions are already the total") and `DEFAULT_SETS` = `NO_SETS`, `TRACKING_MODES` (value → dropdown label, `TOTAL_MODE` and `SETS_MODE`) with `DEFAULT_TRACKING_MODE` = `TOTAL_MODE`, `MIN_AGE`/`MAX_AGE` (1–120) and `MAX_COMMENT_LENGTH` (2000, the textarea's `maxlength` as well as the check) in `services.py`. Routes pass these same lists to the templates to populate the dropdowns, so the form options and the server-side validation can never drift apart; the out-of-range message is built from the ends of `REPETITION_CHOICES` for the same reason.

### Users page

`/users` creates the people whose sessions are tracked — a name (unique, compared
case-insensitively) and an age — and lists everyone with their session count and a link
straight to their filtered analytics. Age is a `type="number"` input whose `min`/`max` come
from `MIN_AGE`/`MAX_AGE`, the same constants `create_user` validates against and builds its
error message from, so the field and the check cannot drift. `_age_from_form` in
`routes.py` turns an unparseable age into `0`, which fails that same range check, so a
hand-crafted POST gets the range message rather than an `int()` traceback.

### Create page

`/create` opens with the workout's name and then its **sort of sport** — a
`category` dropdown filled from `category_map()`, so it offers exactly the rows
the table holds. Its field name is `CATEGORY_FIELD` in `routes.py`, and the
route reads it with `DEFAULT_CATEGORY` as the fallback, so a hand-crafted POST
leaving the field out still saves a workout while a value the dropdown cannot
have produced is rejected by `create_workout` with a message built from the
labels the dropdown is filled with. The success flash names it, and the
workout list under the form shows each workout's sort of sport with its colour.

Under the panel sits a second, separate form — a form cannot be nested in
another — posting a `label` (`CATEGORY_LABEL_FIELD`) to `/categories`, which is
`add_category` in `routes.py`: it adds a sort of sport and redirects straight
back to `/create`, where the dropdown above now offers it. `create_category`
derives the stored `value` from the label (lowercased, punctuation to hyphens)
and rejects a label, or a value, that a category already has — so
"Trail running" and "trail-running" cannot become two sorts that colour the
same. **The colour is assigned, not asked for**: the first entry of
`CATEGORY_PALETTE` no category is wearing yet, so the seeded four keep theirs
and every addition is told apart on the map without a colour picker on the
form; once the palette is used up it starts over rather than leaving a category
colourless. A new sort of sport goes last, which is where it then sits in every
dropdown, in the legend and in the map's tie-break. There is no delete: nothing
in the app removes a category, and `label_for_category` covers one removed by
hand.

Besides the free-text exercise fields, `/create` lists every exercise name already in the
log as a chip, from `known_exercise_names()` — the exercises of existing workouts *and*
extras logged on the track page, deduplicated and sorted case-insensitively. A chip carries
its name in `data-exercise` and a single delegated click handler fills the first empty
exercise field (or appends one), skipping names already on the form; `data-*` rather than
an inline `onclick` argument is what keeps names like `Farmer's carry` from breaking the
markup. The chips need JS, so `create_workout` also drops duplicate names
case-insensitively server-side.

**Workouts are shared; sessions belong to a user.** A `Workout` is a template anyone can
perform — and the sort of sport is the template's, not the session's — so
`/create` is not per-user and `known_exercise_names()` spans everybody. What is
per-user is the `WorkoutSession`: `user_id` is `nullable=False`, so every session is logged
against a person, and deleting a user cascades away their sessions and logs while leaving
the workout templates alone.

### Track page

`/track` does **not** ask for the sort of sport: it is the workout's, picked on
the create page, so each option of the workout dropdown names it
("Randori · Judo") and `log_session` copies it onto the session. The success
flash names it all the same.

`/track` opens with a `user_id` dropdown naming who trained — sessions cannot exist without
one, so the page renders "You need a user first" (and no form at all) until a user exists,
the same way it already did for workouts. `USER_FIELD` in `routes.py` is the single source
of that field name, shared with the analytics filter.

Below it sits the **counting mode** — a `tracking_mode` dropdown offering
`TRACKING_MODES`, at the top of the form because it changes what every field
under it means. Counting a *total* (the default) the repetitions dropdown carries
the whole figure for the exercise; counting in *sets* each exercise also gets a
`sets-<exercise id>` dropdown and its repetitions are the repetitions of one set,
the two multiplying into what is logged. The number of sets is **per exercise**,
so 4×10 squats and 3×12 lunges belong to the same session.

`_tracking_mode` in `routes.py` reads the field, falling back to
`DEFAULT_TRACKING_MODE` for anything the dropdown cannot have produced, and
`_sets_from_form` returns `{}` outside sets mode — a browser without JS submits
the sets column regardless, so the mode, not the presence of the fields, is what
decides. The repetitions are validated **per set**, against `REPETITION_CHOICES`
as before, so 20 sets of 120 is a legitimate 2400-repetition entry even though no
dropdown offers that number. A small script hides and `disabled`s the sets column
for a total (the `hide-sets` class in `style.css` closes the row's grid back up
over it) and relabels the reps column "reps / set" in sets mode.

Below that, `/track` renders a `reps-<exercise id>` and a `weight-<exercise id>` dropdown for the exercises of **every** workout, in one form. A small inline script hides and `disabled`s the fieldsets of the workouts that aren't selected, so only the relevant fields are submitted. Without JS all fields are submitted, so `log_session` deliberately ignores exercise ids that don't belong to the chosen workout while requiring one entry for every exercise that does.

The weight column opens on a **"none" option ahead of `WEIGHT_CHOICES`**, whose
form value is the empty string (`NO_WEIGHT_VALUE` in `routes.py`, passed to the
template so the option and the parser cannot drift). Leaving it alone records
bodyweight: `_weight` in `routes.py` turns that blank into `NO_WEIGHT`, the log's
`weight` is NULL, and the exercise is counted in repetitions alone — no weight
moved, no share of a weight total, no best session. Unlike the repetitions the
weight is **optional per exercise**: an id missing from `weights_by_exercise` is
logged at `DEFAULT_WEIGHT` (= `NO_WEIGHT`) rather than rejected, so a hand-crafted
POST without the field still logs a session rather than failing. `_check_weight`
lets `NO_WEIGHT` through and still rejects 0, which is *not* a way to say "none".
The success flash drops its weight clause entirely when `total_weight` is 0.

Below that sits the extra-exercises fieldset: repeatable `extra-name` / `extra-reps` / `extra-weight` rows, positionally zipped, for exercises done only in this session. One empty row is rendered server-side (so it works without JS) and `addExtraExercise()` clones the `#extra-row-template` for more. Blank rows are dropped, and `log_session` rejects an extra whose name is already an exercise of the workout, or repeated twice, so nothing gets double counted.

`extra_exercises` takes `(name, reps)`, `(name, reps, weight)` *or*
`(name, reps, weight, sets)` tuples, the weight and sets again defaulting to
`DEFAULT_WEIGHT` and `DEFAULT_SETS` — which is also what a row whose weight field
is missing, or left at "none", gets, rather than the row being dropped along with
it. An extra row carries a sets dropdown like any other exercise, read only in
sets mode.

Last on the form is an optional free-text `comment` about the session. `log_session`
strips it and stores a blank one as **NULL, not `""`**, which is what lets
`session_comments` select the sessions that actually have something to say.

#### Correcting a session

`/track/<session_id>` is the same route, the same template and the same form,
opened on a session that already exists — the "Correct this session" link under
every session in the analytics day panel. `track(session_id)` looks the session
up with `get_session`, hands the template `editing=session_form(session)` (None
when tracking a new one, which is what every field branches on to pre-select
itself) and saves through `update_session` instead of `log_session`. The
headline, the lede and the submit button change with it, and a Cancel link goes
back to the day. A session id nothing answers to flashes and redirects to
`/analytics`, the way an unknown day there renders without its panel.

`session_form` returns the form's **own** fields rather than the stored ones,
which is the whole trick: in sets mode the repetitions of a dropdown are the
repetitions of one set, so that is what comes back, and re-saving an untouched
form logs exactly what is already there (a test asserts that round trip). A
session with any exercise counted in sets opens in sets mode, an exercise
logged as a total inside it reading back as one set of that total. Extras come
back as filled-in rows with one empty row after them; clearing a name drops
that row, since blank rows are dropped as always.

`update_session` takes exactly `log_session`'s arguments — `_fill_session` is
the half they share, validating everything and building every log *before*
assigning anything, so a rejected correction leaves the session exactly as it
was. The logs are **replaced wholesale** rather than patched (the cascade
deletes the old ones), which is what lets the workout itself be corrected: the
new logs belong to the exercises of the workout now chosen, and the sort of
sport is copied from it again. Saving redirects to the analytics page open on
the day the session now falls on. `date_choices(include=...)` is what keeps the
date dropdown honest for a session older than its 31-day window — without it
saving would silently move the session to a date the dropdown does offer.

`_repetitions_from_form`, `_weights_from_form`, `_sets_from_form` (all three over the shared `_by_exercise_id`) and `_extra_exercises_from_form` in `routes.py` do the field parsing; `REPS_FIELD_PREFIX`, `WEIGHT_FIELD_PREFIX`, `SETS_FIELD_PREFIX`, `EXTRA_NAME_FIELD`, `EXTRA_REPS_FIELD`, `EXTRA_WEIGHT_FIELD`, `EXTRA_SETS_FIELD`, `MODE_FIELD`, `CATEGORY_FIELD` and `CATEGORY_LABEL_FIELD` (both on the create page), `USER_FIELD`, `DAY_FIELD` (the analytics query string's open day) and `COMMENT_FIELD` are the single source of the field-name conventions.

### Analytics page

A `user_id` dropdown at the top reloads the page as `/analytics?user_id=N` (a plain GET
form with a submit button, so it works without JS; `onchange` just submits it early), and
every section below is then computed for that user alone. No `user_id`, a blank one, or an
id that no longer exists all fall back to "All users" — `_selected_user_id` in `routes.py`
returns `None` and `services.get_user` returns `None` for an unknown id.

A `day` in the query string opens the activity map on that date — `/analytics?user_id=N&day=2026-09-01#day` — which is what a click on a cell produces. `_selected_day` in `routes.py` parses it and falls back to `None` for anything that isn't a date, the way an unknown user id falls back to "All users", so a hand-edited link renders the page without its panel rather than raising. The user filter carries the open day through in a hidden field, so switching person keeps the day rather than closing it.

Each analytics service takes `user_id: int | None = None`, and `_for_user(query, user_id)`
applies the filter (before grouping, so it lands in the WHERE clause) or leaves the query
alone for `None`. `exercise_repetitions` joins `WorkoutSession` in its totals queries — a
join it does not otherwise need — purely so those totals can be filtered too.

Picking a user narrows *what is listed*, not just the counts. Across everyone the two
tables double as a list of what exists, so rows at zero belong there; on one person's page
they are noise:

- `workout_frequency` lists only the workouts the selected user has performed — an inner
  join for a `user_id`, an `outerjoin` for everyone.
- `exercise_repetitions` drops any exercise with `times` 0, which is exactly the set that
  would otherwise render as "Not performed yet" (`heatmap` is `None` for the same rows).
  An exercise logged with 0 repetitions was still *part of* a session, so it stays.

Either section can therefore come out empty for a user who has tracked nothing, and each
renders its own "hasn't performed … yet" message instead of the across-everyone one.

Five sections, in this order (a test asserts the order):

1. `activity_map()` — heatmap of the last 365 days, one cell per day counting
   sessions. A cell carries **two** things: its `level` shades it by how many
   sessions the day held, and its `category` hues it by which sort of sport
   they were. A day of several sorts takes the one done most, the stored
   category order breaking a tie so the colour never depends on the order rows
   came back in; a day with no session has `category` `None`. The
   `category_legend` macro in `analytics.html` draws the key beneath the grid —
   one full-shade cell per row of `category_map()`, so the legend cannot list a
   colour the map doesn't use, and a sort of sport added on the create page
   appears in both without a line of CSS.

   Every day that holds a session is a **link to its own details**, rendered by
   the `day_detail` macro directly under the map (so the page still has five
   sections — the panel belongs to the map, not beside it). A day with nothing
   on it stays a plain span: only the cells worth opening are clickable, which
   is also why the grid needs no JS for any of this. `day_sessions(day,
   user_id)` is what it lists — every session logged that day, oldest-logged
   first, each with its sort of sport, workout, who trained, duration, feeling,
   comment, a link to correct it (`/track/<id>`, which is why every entry
   carries the session's `id`) and one row per exercise: the name (tagged when
   it was an extra),
   the repetitions — written `4 × 12 = 48` when the session was counted in
   sets, since `sets` and `repetitions_per_set` survive to say so — and the
   extra weight, or "bodyweight" where the column is NULL. The figures are read
   off the model properties rather than re-summed in SQL, so a day can't
   disagree with `total_repetitions`, `total_weight` or `weight_moved`
   elsewhere on the page. The panel obeys the user filter like everything else,
   which is why a day can be a link on one person's map and say "Nothing logged
   on this day by …" once another is picked.
2. `workout_frequency()` — sessions per workout, most frequent first, including workouts never performed. Each row also carries `feelings`, a count per value of `FEELINGS`, rendered as Good/Okay/Bad columns; the total session count above the table is just `frequency | sum(attribute='count')` in the template, not a service call.
3. `feeling_trend()` — one entry per day for the last `TREND_DAYS` (30) days, oldest first; rest days have `sessions` 0 and `score`/`feeling` `None`, and a day with several sessions gets their average score with the label rounded half-up.
4. `exercise_repetitions()` — one entry per exercise, grouped **by exercise name**, so an exercise appearing in several workouts (or logged as an extra) is reported once. `workouts` names where the repetitions actually **came from** — the workouts of the sessions the exercise was logged in — not every workout that happens to contain an exercise of that name. An extra belongs to no workout, so an exercise done only as an extra lists none; otherwise doing "Squats" as an extra during Arm day would label it "Leg day" and imply a workout that was never performed. An exercise nobody has performed has no sessions to go on and falls back to the workouts it belongs to, which is the only thing there is to say about it — that is what the "Not performed yet · Leg day" caption shows. Alongside the totals (`repetitions`, `weight`, `times`, `workouts`, `extra`) each row carries `heatmap`: its own calendar grid of the last `EXERCISE_HEATMAP_DAYS` (365) days, counting repetitions per day and summing them when an exercise landed twice on one date (possible across two sessions). `heatmap` is `None` for an exercise never performed, which the template renders as "Not performed yet" with no grid. Each row also carries `trend` from **`_repetition_trend`**: it splits the exercise's own history — first performed date to last — into two equal-length halves and compares the repetitions in each, giving `direction` (`"up"`, `"down"`, `"similar"` or `None`), both half totals, the `split` date and `change` as a fraction. Within ±`REPETITION_TREND_TOLERANCE` (15%) counts as `"similar"`; `direction` is `None` when everything falls on one date, and `change` is `None` when the earlier half is 0 (no baseline to be a percentage of), which the badge renders as a direction with no percentage. The trend reads the whole history, not just the heatmap window, so an old session can shape a trend whose grid looks empty.

   Next to the repetitions each row carries `weight` — the weight moved over the
   exercise's whole history, `weight_moved` summed — `weighted`, whether any set
   carried an extra weight at all, and `best_session`, the one session that
   accounts for most of the weight, as `{"weight": int, "date": date}` (a `date`,
   formatted in the template, the way `session_comments` carries one). Grouping is
   **per session, not per date**: two sessions on one day compete rather than being
   merged the way the heatmap merges them, and a weight matched again is reported
   at the later date. Sessions done at bodyweight are not candidates, so a best
   session always carried something. `best_session` is `None` for an exercise never
   performed, exactly as `heatmap` is, *and* for one never performed with a weight;
   `weighted` is `False` for both, and the template hangs the whole weight clause —
   "… kg moved · best session …" — off `weighted`, so an exercise only ever done at
   bodyweight is captioned in repetitions alone rather than at 0 kg. The section's
   "kg moved in total" stat disappears the same way when nothing was ever carried.
   Both figures read the whole history, so a best session can predate the grid it
   is captioning.

   **Repetitions are counted the same either way**: the grouping is by exercise
   name alone, so the same exercise done weighted one session and at bodyweight the
   next is one row whose `repetitions` and `times` cover both, and only its
   `weight` is restricted to the sets that carried something.

   The function merges five queries in Python: workout membership, linked totals,
   extra totals, and linked and extra **per session** — the last two carrying the
   session's date and id, which is what lets the per-date heatmap counts and the
   per-session best both come out of one grouping.

5. `session_comments()` — the sessions carrying a free-text note, **most recent first**
   (same-day sessions newest-logged first, for which the session id stands in). One entry
   per comment: `date` (a `date`, formatted in the template), `workout`, `feeling`, `user`
   and `comment`. Sessions with no comment are left out, so this is a log of what was
   written, not of what was tracked. `user` is always carried but the template prints it
   only in the across-everyone view — with a user selected the page already says whose it
   is. The text renders with `white-space: pre-wrap`, so line breaks typed on the track
   page survive.

   Only the newest `limit` notes come back, `COMMENT_LIMIT` (5) by default — this is the
   one section that does *not* list everything it knows about. The cut is a SQL LIMIT
   after the `order_by`, so it keeps the newest rather than whichever rows came back
   first, and it lands after `_for_user`: picking a user shows their last 5, not their
   share of everyone's last 5. Routes pass `COMMENT_LIMIT` to the template as
   `comment_limit` so the section's "The last 5 notes…" copy is built from the same
   constant the query uses and cannot drift from it.

Both heatmaps come from **`_calendar_weeks(counts, end, days, categories=None)`**, which buckets a `{date: count}` mapping into Monday-first weeks of `{"date", "count", "level", "category"}` cells (`None` pads the first partial week), plus the window's `max` and `months` — one `{"label": "Sep 2025", "weeks": n}` per run of week columns, which the template lays out as the x axis above the grid. A week is attributed to the month of its first day, and the spans always sum to the number of columns.

Month-label alignment is CSS, not magic numbers: `--cell` and `--cell-gap` define the grid, and each label's width is `calc(var(--weeks) * (var(--cell) + var(--cell-gap)) - var(--cell-gap))` with `--weeks` set inline. Change the cell size and the axis follows. Labels are deliberately not clipped — a full month is wide enough for "May 2026" at the current font size, and only the trailing partial month is narrow, with nothing after it to overlap. Levels are 0-4 relative to that grid's own busiest day, so an exercise's shading is relative to its own best day, not to other exercises. `categories` is the optional `{date: category value}` mapping that colours the activity map; a grid built without it — every per-exercise one, where a cell counts repetitions and no one sort of sport owns it — gets `category` `None` on every cell and keeps the default green scale. Counts outside the window are ignored, so an all-time total can be non-zero while its grid is empty. The `heatmap` Jinja macro in `analytics.html` renders any of these grids, with the `unit` argument naming what a cell counts ("session" or "repetition"); a cell that carries a category looks it up in `categories` (the `category_map()` the route passed in), carries that row's colour as an inline `--heat` and has its label in the tooltip. Its `linked` argument — true for the activity map alone — turns the non-empty days into `<a>` cells pointing at `?day=`, and the open day's cell carries a `selected` class; an exercise grid's days are never links, since a cell there is repetitions, not sessions to open.

The shading itself is one CSS scale rather than five: `--heat` is the colour a
grid is shaded towards, `--heat-0` the empty-day grey, and levels 1-3 are
`color-mix`es between the two, so a cell only has to redefine `--heat` and the
whole ramp follows. A cell of the activity map does that **inline**, from the
colour stored on its category, which is what lets a sort of sport added on the
create page be coloured without a rule in `style.css` — there are no `.cat-*`
rules and no `--cat-*` variables any more. Change a category's colour in the
table and the map, the legend and the create page's swatches all follow.

`activity_map`, `feeling_trend` and the exercise grids render straight into the template's markup and SVG geometry, computed in Jinja, so changing a returned shape means changing `analytics.html` too. Analytics service functions take an explicit `end` date defaulting to today, which is what lets the tests seed fixed dates.

## Tests

`tests/conftest.py` provides `app` (in-memory DB, pushed app context, dropped after each
test — and seeded with the four default sorts of sport, since `create_app` seeds them),
`client`, and the `user` / `other_user` fixtures ("Alex", 34 and "Sam", 41). Since
`log_session` requires a user, almost every test takes `user`; `test_analytics.py`'s
`two_users` fixture splits one shared workout across both people so the per-user analytics
can be checked against a clean split. `test_services.py` and `test_analytics.py` call service functions directly; `test_routes.py` exercises the HTTP layer via `client` and builds POST bodies with its `track_form` helper. Every service function is expected to have test coverage.

## Entry point

`main.py` holds `create_app()` plus `app.run(debug=True)`. (An earlier `run.py` did this
and is gone; don't reintroduce it.) `app.run(debug=True)` is for local work only — the
container serves the same `main:app` through gunicorn instead.

## Configuration

`create_app` builds its config from the environment, and `tests/test_config.py` covers
every branch of it:

- `APP_ENV=production` means "being served for real". The Dockerfile sets it; `python
  main.py` and the tests do not, so neither needs a secret to keep working. It is
  compared stripped and case-insensitively, so a stray space can't quietly disable the
  check below.
- `SECRET_KEY` signs the session cookie the flash messages ride in. Under
  `APP_ENV=production` an unset key — *or* the `DEV_SECRET_KEY` (`"dev"`) baked into
  `src/__init__.py` — raises `RuntimeError` at startup rather than serving something
  quietly forgeable.
- `SESSION_COOKIE_SECURE` is an opt-in flag, **off** by default on purpose: a cookie
  marked Secure is dropped over plain HTTP, which would make flash messages vanish in
  the default localhost deployment. `SESSION_COOKIE_HTTPONLY` and `SAMESITE=Lax` are
  always on. `_flag` parses the booleans (`1/true/yes/on`).

`test_config` still overrides everything afterwards, so the tests are unaffected.

## Deployment

Four files, all at the repo root: `Dockerfile`, `compose.yaml`, `gunicorn.conf.py`,
`.dockerignore`, plus `.env.example` as the template for the gitignored `.env`.

The Dockerfile is two stages. The build stage runs `uv sync --frozen --no-dev --extra
deploy` against `uv.lock` — `--frozen` fails rather than re-resolving if the lock has
drifted from `pyproject.toml`, so **adding a dependency means re-running `uv lock`** or
the image build breaks. Only `/app/.venv` and the source cross into the run stage, which
therefore ships no uv, no compiler and no pytest. Both base images are pinned by digest;
the Dockerfile's header comment carries the two commands for reading a new one.

The run stage adds a fixed uid/gid 10001 `app` user and `install -d -o app` on
`/app/instance` — that ownership is what a named volume inherits when Docker first
populates it, which is why the compose file uses a named volume and not a bind mount.
Everything else in the image stays root-owned and is read-only to the process
(`read_only: true`, with a `noexec` tmpfs for `/tmp`), so `/app/instance` is the only
writable path and SQLite's `workouts.db` and its journal both live there.

`gunicorn.conf.py` is loaded by `--config`. Two settings are load-bearing rather than
cosmetic: `preload_app = True` so `db.create_all()` runs once before forking instead of
once per worker racing on the same file, and `control_socket_disable = True` because
gunicorn 26 otherwise opens a control socket under `$HOME`, which the app user does not
have and the read-only filesystem would refuse. `forwarded_allow_ips` deliberately keeps
gunicorn's narrow default — never widen it to `*`.

Compose publishes `127.0.0.1:8000:8000`, loopback only. **The app has no authentication
at all**, so that binding is a security control, not a formality: don't change it to
`0.0.0.0` or add a public port. Anything remote belongs behind a reverse proxy that
authenticates first, with `SESSION_COOKIE_SECURE=1` and `FORWARDED_ALLOW_IPS` set to
that proxy.
