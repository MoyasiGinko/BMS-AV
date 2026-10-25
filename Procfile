release: python manage.py migrate --noinput
web: gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 4 --worker-class gthread --threads 4 --timeout 60 --access-logfile - --error-logfile -
worker: celery -A config worker --loglevel=info -P solo
beat: celery -A config beat --loglevel=info
