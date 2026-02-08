#!/bin/sh

# Exit on error
set -e

# Check postgres availability
if [ "$DATABASE" = "postgres" ]
then
    echo "Waiting for postgres..."
    while ! nc -z $DB_HOST $DB_PORT; do
      sleep 0.1
    done
    echo "PostgreSQL started"
fi

# Run migrations
echo "Running migrations..."
python manage.py migrate

# --- DELETED: Auto-seed logic ---
# We removed the DEMO_MODE block here.
# Seeding is now strictly triggered by the 'Demo Login' view.

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Start server
exec "$@"
