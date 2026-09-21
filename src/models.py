from datetime import date as date_type

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

FEELINGS = ("good", "okay", "bad")

# Numeric score per feeling, used to plot the feeling trend. Higher is better.
FEELING_SCORES = {"bad": 1, "okay": 2, "good": 3}

# The sorts of sport there are. Unlike the feelings these live in the database,
# in the `Category` table, because the create page can add one; the tuple below
# is only what an empty database is seeded with, in this order, by
# `services.ensure_categories()`. Each entry is (value, label, colour): the
# value is what a workout and a session store, the label is what the dropdowns
# and the legend show, and the colour is what the activity map shades a day of
# that sport towards.
DEFAULT_CATEGORIES = (
    ("weights", "Weights", "#2f66b5"),  # blue
    ("judo", "Judo", "#c0392b"),  # red
    ("mobility", "Mobility", "#7a4fb8"),  # violet
    ("other", "Others", "#1c1f26"),  # black
)
DEFAULT_CATEGORY = "weights"  # what the create form's dropdown opens on

# Colours handed to the sorts of sport added on the create page, in this order:
# `services.create_category` takes the first one no category is using yet, so
# the four seeded colours above are never handed out again and a new sort is
# told apart from them on the map. They run out after this many additions, at
# which point the palette is reused from the start.
CATEGORY_PALETTE = (
    "#1f6b44",  # green
    "#c2761c",  # amber
    "#0f8fa8",  # teal
    "#a8326e",  # magenta
    "#5b6b1f",  # olive
    "#7b4a21",  # brown
    "#3b4bb5",  # indigo
    "#8a6a1f",  # ochre
)
# What a value no category row explains is drawn in — only reachable through a
# session logged under a sort of sport that was later deleted from the table.
UNKNOWN_CATEGORY_COLOR = "#8a94a6"


class Category(db.Model):
    """A sort of sport, e.g. 'Judo' — what a workout is, and a session with it.

    `value` is the stable, url-safe form stored on `Workout.category` and
    `WorkoutSession.category`; `label` is what is shown. `position` is the
    order the dropdowns and the activity map's legend list them in, and the
    tie-break for a day that held two sorts of sport in equal numbers.
    `color` is what the map shades such a day towards.
    """

    id = db.Column(db.Integer, primary_key=True)
    value = db.Column(db.String(40), unique=True, nullable=False)
    label = db.Column(db.String(60), unique=True, nullable=False)
    color = db.Column(db.String(20), nullable=False)
    position = db.Column(db.Integer, nullable=False)

    def __repr__(self) -> str:
        return f"<Category {self.value}>"


def category_by_value(value: str) -> "Category | None":
    """The category with that value, or None for one the table doesn't know."""
    return Category.query.filter_by(value=value).first()


def label_for_category(value: str) -> str:
    """The label of that sort of sport, falling back to the bare value.

    A workout or session can only be stored with a value that existed when it
    was saved, so the fallback is what a category deleted afterwards leaves
    behind — the raw value rather than a blank.
    """
    category = category_by_value(value)
    return category.label if category else value


class User(db.Model):
    """A person whose sessions are tracked. Workouts themselves are shared."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    age = db.Column(db.Integer, nullable=False)
    sessions = db.relationship(
        "WorkoutSession", backref="user", cascade="all, delete-orphan", lazy=True
    )

    def __repr__(self) -> str:
        return f"<User {self.name}>"


class Workout(db.Model):
    """A workout template, e.g. 'Leg day', made up of exercises.

    `category` is the sort of sport performing it is — the value of one of the
    `Category` rows, picked on the create page. Every session of the workout is
    logged under it, which is what the activity map colours a day by.
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    category = db.Column(  # the value of one of the Category rows
        db.String(40), nullable=False, default=DEFAULT_CATEGORY
    )
    exercises = db.relationship(
        "Exercise", backref="workout", cascade="all, delete-orphan", lazy=True
    )
    sessions = db.relationship(
        "WorkoutSession", backref="workout", cascade="all, delete-orphan", lazy=True
    )

    @property
    def category_label(self) -> str:
        """The label of the sort of sport this workout is."""
        return label_for_category(self.category)

    def __repr__(self) -> str:
        return f"<Workout {self.name} category={self.category}>"


class Exercise(db.Model):
    """A single exercise belonging to a workout, e.g. 'Squat'."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    workout_id = db.Column(db.Integer, db.ForeignKey("workout.id"), nullable=False)
    logs = db.relationship(
        "SessionExercise", backref="exercise", cascade="all, delete-orphan", lazy=True
    )

    def __repr__(self) -> str:
        return f"<Exercise {self.name}>"


class WorkoutSession(db.Model):
    """One performed instance of a workout, by one user (tracked on /track).

    `category` is the sort of sport it was, copied from the workout when the
    session is logged. It is stored on the session rather than read back
    through the workout so that history survives: a workout re-labelled as a
    different sport tomorrow leaves everything already logged under it
    untouched. The activity map colours each day by it.
    """

    id = db.Column(db.Integer, primary_key=True)
    workout_id = db.Column(db.Integer, db.ForeignKey("workout.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    date = db.Column(db.Date, nullable=False, default=date_type.today)
    duration_minutes = db.Column(db.Integer, nullable=False)  # 10-90
    feeling = db.Column(db.String(10), nullable=False)  # good / okay / bad
    category = db.Column(  # the workout's sort of sport, as at logging time
        db.String(40), nullable=False, default=DEFAULT_CATEGORY
    )
    comment = db.Column(db.Text)  # free text, NULL when the field was left blank
    logs = db.relationship(
        "SessionExercise", backref="session", cascade="all, delete-orphan", lazy=True
    )

    @property
    def total_repetitions(self) -> int:
        """Repetitions across every exercise performed in this session."""
        return sum(log.repetitions for log in self.logs)

    @property
    def total_weight(self) -> int:
        """Weight moved across every exercise performed in this session.

        Exercises done with no extra weight contribute nothing, so a session of
        bodyweight exercises alone totals 0.
        """
        return sum(log.weight_moved or 0 for log in self.logs)

    @property
    def category_label(self) -> str:
        """The label of the sort of sport this session was."""
        return label_for_category(self.category)

    def __repr__(self) -> str:
        return (
            f"<WorkoutSession workout={self.workout_id} "
            f"user={self.user_id} date={self.date} category={self.category}>"
        )


class SessionExercise(db.Model):
    """Repetitions logged for one exercise within one session.

    Either `exercise_id` points at an exercise of the workout, or `extra_name`
    carries the name of an extra exercise done in this session only — added on
    the track page without becoming part of the workout template.

    `weight` is the extra weight carried for those repetitions, and is NULL
    when there was none — a bodyweight exercise, which is what the track page
    pre-selects. A NULL weight is not a weight of 0: it means the exercise
    counts in repetitions only, and it is left out of every weight figure on
    the analytics page rather than being totalled as nothing.

    `repetitions` is always the repetitions actually performed, whichever way
    the track page counted them. `sets` says how they were split up: NULL when
    the session was counted as a total per exercise, or the number of sets the
    repetitions were done in, `repetitions` then being that many equal sets.
    Analytics read `repetitions` alone, so counting in sets changes what goes
    into the total, never how it is reported.
    """

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer, db.ForeignKey("workout_session.id"), nullable=False
    )
    exercise_id = db.Column(db.Integer, db.ForeignKey("exercise.id"))
    extra_name = db.Column(db.String(120))  # set only when exercise_id is None
    repetitions = db.Column(db.Integer, nullable=False)  # performed in total
    sets = db.Column(db.Integer)  # 1-20, or NULL when counted as a total
    weight = db.Column(db.Integer)  # 1-200, or NULL for no extra weight

    @property
    def is_extra(self) -> bool:
        """True for an exercise logged only in this session."""
        return self.exercise_id is None

    @property
    def name(self) -> str:
        return self.extra_name if self.is_extra else self.exercise.name

    @property
    def tracked_in_sets(self) -> bool:
        """True when this exercise was counted in sets rather than as a total."""
        return self.sets is not None

    @property
    def repetitions_per_set(self) -> int | None:
        """The repetitions of one set, or None when counted as a total.

        `repetitions` is the number of sets multiplied by this, so the division
        is exact.
        """
        if self.sets is None:
            return None
        return self.repetitions // self.sets

    @property
    def has_weight(self) -> bool:
        """True when an extra weight was carried, False for bodyweight."""
        return self.weight is not None

    @property
    def weight_moved(self) -> int | None:
        """The extra weight, once per repetition of it, or None without one.

        This is what the analytics page reports as an exercise's total weight,
        so a heavy set of few repetitions and a light set of many are
        comparable. It is None — not 0 — for an exercise done with no extra
        weight, so such a set is reported in repetitions alone instead of
        counting as nothing moved. An exercise logged at 0 repetitions moved
        nothing, whatever weight was picked for it.
        """
        if self.weight is None:
            return None
        return self.repetitions * self.weight

    def __repr__(self) -> str:
        return (
            f"<SessionExercise {self.name} reps={self.repetitions} "
            f"sets={self.sets} weight={self.weight}>"
        )
