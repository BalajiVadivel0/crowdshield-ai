# CrowdShield AI

CrowdShield AI is a mobile-first AI-powered crowd safety and early warning system designed to prevent crowd stampedes and dangerous congestion.

This is a monorepo containing:
- `mobile/`: Flutter mobile application (coming in future phases)
- `backend/`: Python FastAPI backend providing real-time AI processing and WebSocket streams

## Project Phases
- **Phase 0:** Repository Audit
- **Phase 1:** Core AI Pipeline REST Integration (Completed)
- **Phase 2:** Real-Time WebSocket Infrastructure (Completed)
- **Phase 3:** Authentication & Role-Based Authorization (Completed)

## Quick Start

### Backend Development Environment
To get the backend API running locally, follow these steps:

1. **Navigate to the backend directory:**
   ```bash
   cd backend
   ```
2. **Set up a virtual environment:**
   ```bash
   python -m venv venv
   # Windows:
   .\venv\Scripts\activate
   # macOS/Linux:
   source venv/bin/activate
   ```
3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Environment Variables:**
   ```bash
   cp .env.example .env
   # Edit .env to set a strong JWT_SECRET
   ```
5. **Database Setup:**
   ```bash
   alembic upgrade head
   ```
6. **Run the Server:**
   ```bash
   uvicorn app.main:app --reload
   ```
7. **View Documentation:**
   Open `http://127.0.0.1:8000/docs` in your browser to interact with the API Swagger UI.

For more detailed backend instructions, refer to the [Backend README](backend/README.md).