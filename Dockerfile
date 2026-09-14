# syntax=docker/dockerfile:1
#
# Two stages: uv resolves and installs the dependencies into a virtualenv in
# the first, and only that virtualenv and the application source cross into the
# second. The image that ships therefore carries no uv, no compiler, no lock
# file and no test suite — nothing that is only needed to build it.
#
# Both base images are pinned by digest, not just by tag, so a rebuild gets the
# bytes that were reviewed rather than whatever the tag points at today. To
# move to a newer Python, pull the tag and read the new digest off it:
#
#   docker pull python:3.14-slim
#   docker image inspect python:3.14-slim --format '{{index .RepoDigests 0}}'

# ------------------------------------------------------------------- build

FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 AS build

# The uv binary alone, from its own published image — nothing else from it
# reaches the build, and none of it reaches the final image.
COPY --from=ghcr.io/astral-sh/uv@sha256:99ea34acedc870ba4ad11a1f540a1c04267c9f30aadc465a94406f52dfda2c36 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Only the two files that describe the dependencies, so this layer is cached
# until they actually change.
COPY pyproject.toml uv.lock ./

# --frozen fails rather than silently re-resolving if uv.lock has drifted from
# pyproject.toml, so the image can only be built from dependencies that were
# locked and reviewed — uv verifies each against the hashes in the lock file.
# --no-dev leaves pytest out; --extra deploy pulls gunicorn in.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra deploy

# -------------------------------------------------------------------- run

FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6

LABEL org.opencontainers.image.title="Training Log" \
      org.opencontainers.image.description="Flask workout diary: users, workouts, sessions and analytics."

# A fixed uid/gid, so the ownership of the database volume survives a rebuild
# and can be reasoned about from the host. High enough not to collide with a
# system account the base image may add later.
RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    # Tells create_app this is a real deployment: it then refuses to start on
    # the dev SECRET_KEY baked into the source. Nothing else reads it.
    APP_ENV=production

WORKDIR /app

COPY --from=build --chown=root:root /app/.venv /app/.venv
COPY --chown=root:root main.py gunicorn.conf.py ./
COPY --chown=root:root src ./src

# The one writable path: SQLite needs to create workouts.db and its journal
# beside it. Owned by the app user so a named volume mounted here inherits
# that ownership when Docker first populates it; everything else in the image
# stays owned by root and read-only to the process.
RUN install -d -o app -g app -m 0755 /app/instance

USER app:app

EXPOSE 8000

# Hits a page that actually queries the database, so a wedged SQLite file
# fails the check instead of passing on a bare TCP accept. Uses the venv's
# own Python — the image deliberately has no curl or wget.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request as r; r.urlopen('http://127.0.0.1:8000/create', timeout=4).read(1)"]

CMD ["gunicorn", "--config", "gunicorn.conf.py", "main:app"]
