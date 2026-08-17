# CrowdShield AI Backend

FastAPI backend for CrowdShield AI, providing real-time crowd safety analysis, AI pipeline integration (Risk Engine, Prediction Engine, Intelligence Service), and WebSocket broadcasting.

## Prerequisites
- **Python 3.10+** (3.11+ is highly recommended)
- **SQLite** (Used by default via `aiosqlite`)

## Setting Up the Development Environment

### 1. Create and Activate a Virtual Environment
It is recommended to use a virtual environment to manage dependencies.

**Windows:**
```powershell
python -m venv venv
.\venv\Scripts\activate
```

**Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install Dependencies
Install the required Python packages from `requirements.txt`:
```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy the example environment file and customize it if necessary:
```bash
cp .env.example .env
```
Ensure you have a secure `JWT_SECRET` set in your `.env` file for authentication.

### 4. Database Setup & Migrations
The project uses SQLite and Alembic for schema migrations. To initialize or upgrade your local database to the latest schema:
```bash
alembic upgrade head
```
*Note: This will create a `test.db` file in the root of the backend directory.*

## Running the Application Locally

Start the FastAPI server with auto-reload enabled:
```bash
uvicorn app.main:app --reload
```
The API will be available at: `http://127.0.0.1:8000`

### Interactive API Documentation
Once the server is running, you can access the automatically generated Swagger UI documentation at:
- **Swagger UI:** `http://127.0.0.1:8000/docs`
- **ReDoc:** `http://127.0.0.1:8000/redoc`

## Testing

The backend includes a comprehensive suite of unit and integration tests written in `pytest`. To run the tests, execute:
```bash
# Using the pytest module ensures the current directory is on the python path
python -m pytest
```

*(Note: During tests, an in-memory SQLite database is used by default.)*

## Key Architecture Components

- **Auth & Authorization:** Role-based access control (Citizen vs. Authority) powered by JWT tokens (`app/api/v1/endpoints/auth.py`).
- **REST Endpoints:** Found in `app/api/v1/endpoints/`.
- **Real-Time WebSockets:** Managed by `app/services/websocket_manager.py` and `ws.py` to push dynamic updates to Authority and Citizen dashboards.
- **AI Engines:** Found in `app/ai/`. These include the `risk_engine` and `prediction_engine` that calculate crowd safety metrics.

