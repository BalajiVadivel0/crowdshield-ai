# CrowdShield AI Backend

FastAPI backend for CrowdShield AI.

## Prerequisites
- **Python 3.11+** is highly recommended and expected for this project.

## Running Locally

1. Create a virtual environment:
   ```bash
   python -m venv venv
   ```
2. Activate the virtual environment:
   - Windows: `.\venv\Scripts\activate`
   - Linux/Mac: `source venv/bin/activate`
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Start the server:
   ```bash
   uvicorn app.main:app --reload
   ```
