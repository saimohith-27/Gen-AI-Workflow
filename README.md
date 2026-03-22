# Gen-AI-Workflow (Prototype)

This Flask prototype accepts citizen complaints, sends them to a GenAI (Gemini-like) API for analysis and routing, and displays the results.

Quick start

1. Create a virtual environment and install dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

2. (Optional) Create a `.env` file with:

```
GEMINI_API_KEY=your_api_key_here
GEMINI_ENDPOINT=https://api.gemini.example/v1/generate
FLASK_SECRET=replace-with-secret
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key_here
# Optional fallback if service role key is not used:
# SUPABASE_ANON_KEY=your_anon_key_here
```

3. Run the app:

```bash
python app.py
```

4. Open `http://localhost:5000`

Notes

- The app currently uses an in-memory store for demo purposes. Replace with your persistent DB where marked by `???` in `app.py`.
- Update `send_to_gemini()` in `app.py` to match your actual LLM API's payload/response format.