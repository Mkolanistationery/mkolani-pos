# Mkolani POS Advanced

Flask + SQLite business management platform.

## Local run
1. Install Python 3.11+
2. `python -m venv venv`
3. Windows: `venv\Scripts\activate`
4. `pip install -r requirements.txt`
5. `python app.py`
6. Open `http://127.0.0.1:5000`

## Environment variables
- `SECRET_KEY` = strong random secret
- `DATABASE_PATH` = optional SQLite path
- `FLASK_DEBUG` = `1` only for local development
- `PORT` = Render supplies this automatically

## Beem
Configure Beem API key, secret key and sender ID in Business Settings or the global settings in the database. The existing Beem endpoint from the original project is retained.

## Important
Make a backup of the existing `pos.db` before replacing your local project. The application contains migrations intended to preserve the original users, receipts and settings schema while adding advanced modules.
