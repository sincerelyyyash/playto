/**
 * PM2 ecosystem: Gunicorn (HTTP API) + Celery worker + Celery beat.
 * Postgres / Redis are expected via .env (e.g. managed services), not started here.
 *
 * Prerequisites:
 *   - Python venv at ./.venv with deps: pip install -r requirements.txt
 *   - .env with DATABASE_URL, CELERY_BROKER_URL, CELERY_RESULT_BACKEND, SECRET_KEY, etc.
 *   - Run migrations (and seed) before or after first start:
 *       python manage.py migrate && python manage.py seed_demo
 *
 * API binds to 0.0.0.0:8010 — set ALLOWED_HOSTS in .env to your VM IP or domain.
 *
 * Usage (from this directory):
 *   pm2 start ecosystem.config.cjs
 *   pm2 save && pm2 startup
 */

const path = require('path')
const fs = require('fs')

const ROOT = __dirname
const VENV_BIN = path.join(ROOT, '.venv', 'bin')
const ENV_PATH = path.join(ROOT, '.env')
/** Public HTTP port for Gunicorn (e.g. put nginx in front on 80/443). */
const WEB_PORT = 8010

/**
 * Minimal KEY=value parser (first '=' only). Skips empty lines and # comments.
 * Sufficient for typical django-environ .env files (incl. URLs with '=' in query).
 */
function loadDotEnv(filePath) {
  const env = {}
  if (!fs.existsSync(filePath)) {
    console.warn(`[ecosystem] Missing ${filePath}; processes may lack DATABASE_URL / Celery URLs.`)
    return env
  }
  const text = fs.readFileSync(filePath, 'utf8')
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const eq = trimmed.indexOf('=')
    if (eq <= 0) continue
    const key = trimmed.slice(0, eq).trim()
    let val = trimmed.slice(eq + 1).trim()
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1)
    }
    env[key] = val
  }
  return env
}

const envFromFile = loadDotEnv(ENV_PATH)

module.exports = {
  apps: [
    {
      name: 'playto-gunicorn',
      cwd: ROOT,
      script: path.join(VENV_BIN, 'gunicorn'),
      args: `config.wsgi:application --bind 0.0.0.0:${WEB_PORT} --workers 1`,
      interpreter: 'none',
      env: {
        ...envFromFile,
        PYTHONUNBUFFERED: '1',
      },
      max_restarts: 20,
      exp_backoff_restart_delay: 2000,
    },
    {
      name: 'playto-celery-worker',
      cwd: ROOT,
      script: path.join(VENV_BIN, 'celery'),
      args: '-A config worker --loglevel=info --concurrency=1',
      interpreter: 'none',
      env: {
        ...envFromFile,
        PYTHONUNBUFFERED: '1',
      },
      max_restarts: 20,
      exp_backoff_restart_delay: 2000,
    },
    {
      name: 'playto-celery-beat',
      cwd: ROOT,
      script: path.join(VENV_BIN, 'celery'),
      args:
        '-A config beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler',
      interpreter: 'none',
      env: {
        ...envFromFile,
        PYTHONUNBUFFERED: '1',
      },
      max_restarts: 20,
      exp_backoff_restart_delay: 2000,
    },
  ],
}
