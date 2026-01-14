FROM python:3.12.9-bullseye AS builder


ENV PYTHONFAULTHANDLER=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONHASHSEED=random \
  PIP_NO_CACHE_DIR=off \
  PIP_DISABLE_PIP_VERSION_CHECK=on \
  PIP_DEFAULT_TIMEOUT=100 \
  POETRY_NO_INTERACTION=1 \
  POETRY_VIRTUALENVS_CREATE=false \
  POETRY_CACHE_DIR='/var/cache/pypoetry' \
  POETRY_HOME='/usr/local' \
  POETRY_VERSION=2.1.1

RUN curl -sSL https://install.python-poetry.org | python3 -

WORKDIR /sanic
RUN touch README.md
COPY pyproject.toml /sanic/
RUN poetry install --no-interaction --no-root

COPY . /sanic

RUN mkdir /database

#CMD ["python3", "start.py"]
CMD ["uvicorn", "start:app", "--host", "0.0.0.0", "--port", "7001", "--workers", "6"]
