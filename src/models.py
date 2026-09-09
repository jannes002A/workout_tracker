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
    """A workout template, e.g. 'Leg day', made up of movements."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    movements = db.relationship(
        "Movement", backref="workout", cascade="all, delete-orphan", lazy=True
    )
    sessions = db.relationship(
        "WorkoutSession", backref="workout", cascade="all, delete-orphan", lazy=True
    )

    def __repr__(self) -> str:
        return f"<Workout {self.name}>"


class Movement(db.Model):
    """A single movement (exercise) belonging to a workout."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    workout_id = db.Column(db.Integer, db.ForeignKey("workout.id"), nullable=False)
    logs = db.relationship(
        "SessionMovement", backref="movement", cascade="all, delete-orphan", lazy=True
    )

    def __repr__(self) -> str:
        return f"<Movement {self.name}>"


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
        "SessionMovement", backref="session", cascade="all, delete-orphan", lazy=True
    )

    @property
    def total_repetitions(self) -> int:
        """Repetitions across every movement performed in this session."""
        return sum(log.repetitions for log in self.logs)

    def __repr__(self) -> str:
        return (
            f"<WorkoutSession workout={self.workout_id} "
            f"user={self.user_id} date={self.date}>"
        )


class SessionMovement(db.Model):
    """Repetitions logged for one movement within one session.

    Either `movement_id` points at a movement of the workout, or `extra_name`
    carries the name of an extra movement done in this session only — added on
    the track page without becoming part of the workout template.
    """

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer, db.ForeignKey("workout_session.id"), nullable=False
    )
    movement_id = db.Column(db.Integer, db.ForeignKey("movement.id"))
    extra_name = db.Column(db.String(120))  # set only when movement_id is None
    repetitions = db.Column(db.Integer, nullable=False)  # 0-120

    @property
    def is_extra(self) -> bool:
        """True for a movement logged only in this session."""
        return self.movement_id is None

    @property
    def name(self) -> str:
        return self.extra_name if self.is_extra else self.movement.name

    def __repr__(self) -> str:
        return f"<SessionMovement {self.name} reps={self.repetitions}>"
