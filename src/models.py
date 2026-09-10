from datetime import date as date_type

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

FEELINGS = ("good", "okay", "bad")

# Numeric score per feeling, used to plot the feeling trend. Higher is better.
FEELING_SCORES = {"bad": 1, "okay": 2, "good": 3}


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
    """A workout template, e.g. 'Leg day', made up of exercises."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    exercises = db.relationship(
        "Exercise", backref="workout", cascade="all, delete-orphan", lazy=True
    )
    sessions = db.relationship(
        "WorkoutSession", backref="workout", cascade="all, delete-orphan", lazy=True
    )

    def __repr__(self) -> str:
        return f"<Workout {self.name}>"


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
    """One performed instance of a workout, by one user (tracked on /track)."""

    id = db.Column(db.Integer, primary_key=True)
    workout_id = db.Column(db.Integer, db.ForeignKey("workout.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    date = db.Column(db.Date, nullable=False, default=date_type.today)
    duration_minutes = db.Column(db.Integer, nullable=False)  # 10-90
    feeling = db.Column(db.String(10), nullable=False)  # good / okay / bad
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
        """Weight moved across every exercise performed in this session."""
        return sum(log.weight_moved for log in self.logs)

    def __repr__(self) -> str:
        return (
            f"<WorkoutSession workout={self.workout_id} "
            f"user={self.user_id} date={self.date}>"
        )


class SessionExercise(db.Model):
    """Repetitions logged for one exercise within one session.

    Either `exercise_id` points at an exercise of the workout, or `extra_name`
    carries the name of an extra exercise done in this session only — added on
    the track page without becoming part of the workout template.

    `weight` is the extra weight carried for those repetitions. It is always
    set — an exercise done with no added load is logged at the lowest choice,
    1 — so `weight_moved` can be summed without special-casing.
    """

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer, db.ForeignKey("workout_session.id"), nullable=False
    )
    exercise_id = db.Column(db.Integer, db.ForeignKey("exercise.id"))
    extra_name = db.Column(db.String(120))  # set only when exercise_id is None
    repetitions = db.Column(db.Integer, nullable=False)  # 0-120
    weight = db.Column(db.Integer, nullable=False, default=1)  # 1-200, extra load

    @property
    def is_extra(self) -> bool:
        """True for an exercise logged only in this session."""
        return self.exercise_id is None

    @property
    def name(self) -> str:
        return self.extra_name if self.is_extra else self.exercise.name

    @property
    def weight_moved(self) -> int:
        """The extra weight, once per repetition of it.

        This is what the analytics page reports as an exercise's total weight,
        so a heavy set of few repetitions and a light set of many are
        comparable. An exercise logged at 0 repetitions moved nothing, whatever
        weight was picked for it.
        """
        return self.repetitions * self.weight

    def __repr__(self) -> str:
        return (
            f"<SessionExercise {self.name} reps={self.repetitions} "
            f"weight={self.weight}>"
        )
