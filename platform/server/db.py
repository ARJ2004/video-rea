"""Postgres access: schema + small helpers. One connection pool shared by the web app, the engine loop and the CPU worker."""
import json, os
from contextlib import contextmanager
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

DSN = os.environ.get("VREA_DSN", "postgresql://vrea@/vrea")
pool = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id SERIAL PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'running',
  storyboard JSONB NOT NULL, story_text TEXT, cap_usd NUMERIC NOT NULL DEFAULT 14,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS slots (
  id SERIAL PRIMARY KEY, project_id INT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  key TEXT NOT NULL, kind TEXT NOT NULL, phase TEXT NOT NULL, label TEXT NOT NULL, gate BOOLEAN NOT NULL,
  state TEXT NOT NULL DEFAULT 'waiting', deps TEXT[] NOT NULL DEFAULT '{}', params JSONB NOT NULL DEFAULT '{}',
  round INT NOT NULL DEFAULT 0, note TEXT, chosen_asset INT, ord INT NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (project_id, key));
CREATE TABLE IF NOT EXISTS assets (
  id SERIAL PRIMARY KEY, project_id INT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  slot_key TEXT NOT NULL, round INT NOT NULL DEFAULT 0, kind TEXT NOT NULL, s3_key TEXT NOT NULL,
  meta JSONB NOT NULL DEFAULT '{}', scores JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS runs (
  id SERIAL PRIMARY KEY, project_id INT REFERENCES projects(id) ON DELETE SET NULL, instance_id TEXT, itype TEXT, az TEXT,
  families TEXT, state TEXT NOT NULL, token TEXT NOT NULL, hourly_usd NUMERIC NOT NULL DEFAULT 0, hard_min INT,
  launched_at TIMESTAMPTZ, ready_at TIMESTAMPTZ, ended_at TIMESTAMPTZ, last_seen TIMESTAMPTZ, last_family TEXT,
  last_task_at TIMESTAMPTZ, error TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS tasks (
  id SERIAL PRIMARY KEY, project_id INT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  slot_key TEXT NOT NULL, round INT NOT NULL DEFAULT 0, type TEXT NOT NULL, family TEXT NOT NULL,
  params JSONB NOT NULL DEFAULT '{}', state TEXT NOT NULL DEFAULT 'queued', attempts INT NOT NULL DEFAULT 0,
  run_id INT, progress TEXT, error TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, heartbeat_at TIMESTAMPTZ);
CREATE INDEX IF NOT EXISTS tasks_queue ON tasks (state, family, created_at);
CREATE TABLE IF NOT EXISTS events (
  id SERIAL PRIMARY KEY, project_id INT REFERENCES projects(id) ON DELETE CASCADE, ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  level TEXT NOT NULL DEFAULT 'info', msg TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def init(dsn=None):
    global pool
    pool = ConnectionPool(dsn or DSN, min_size=1, max_size=8, kwargs={"row_factory": dict_row, "autocommit": True}, open=True)
    with conn() as c:
        c.execute(SCHEMA)


@contextmanager
def conn():
    with pool.connection() as c:
        yield c


@contextmanager
def tx():
    with pool.connection() as c:
        with c.transaction():
            yield c


def q(sql, *args):
    with conn() as c:
        return c.execute(sql, args).fetchall()


def one(sql, *args):
    with conn() as c:
        return c.execute(sql, args).fetchone()


def ex(sql, *args):
    with conn() as c:
        c.execute(sql, args)


def J(x):
    return Jsonb(x)


def event(project_id, msg, level="info"):
    ex("INSERT INTO events (project_id, level, msg) VALUES (%s, %s, %s)", project_id, level, msg)


def setting(key, default=None):
    r = one("SELECT value FROM settings WHERE key=%s", key)
    return r["value"] if r else default


def set_setting(key, value):
    ex("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", key, str(value))


def dumps(x):
    return json.dumps(x, ensure_ascii=False, default=str)
