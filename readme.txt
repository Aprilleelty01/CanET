Cantonese to English Translator
================================

The Hong Kong Polytechnic University
LST BALT+AIDA Capstone project
Author: April Lee (class of 2026)

Project overview
----------------
This project is a Cantonese-to-English translator with a local dictionary, fuzzy matching, translation API routing, feedback-based model learning, and a Streamlit web app.

Main components:
- `app.py`: compatibility launcher for the Streamlit web app
- `webpage/streamlit_app.py`: main Streamlit UI
- `backend/main.py`: FastAPI backend
- `backend/translator_utils.py`: translation, corpus, feedback, and STT utilities
- `mobile/`: Flutter client for translation features
- `train/`: corpus enrichment and training helpers

Current feature set
-------------------
- Tone and sentence-final-particle detection
- Sentence type detection with POS refinement
- Simplified-to-traditional normalization
- Fuzzy jyutping / phrase matching
- Local dictionary lookup with API fallback
- Score-based translation API selection
- Random Forest route learning from feedback
- Semantic post-processing
- Translation history logging
- Feedback logging and deduplication
- Advanced search by emotion / attitude / relationship
- Corpus tag search and AI rewrite support
- Speech-to-text support in the web/backend flow

Requirements
------------
- Python 3.9 or newer
- 2 CPU cores minimum
- 4 GB RAM minimum
- 100 MB free disk space minimum
- Network access for online translation engines

Recommended setup
-----------------
Use a virtual environment in the project root:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If you already have `.venv`, you can use that instead:

```bash
.venv/bin/python -m pip install -r requirements.txt
```

Run the web app
---------------
Streamlit web entrypoint:

```bash
python -m streamlit run app.py
```

If your system Python and project environment differ, prefer the venv interpreter explicitly:

```bash
./venv/bin/python -m streamlit run app.py
```

The app usually opens at:
- http://localhost:8501

Run the backend API
-------------------
Start FastAPI directly:

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Useful backend endpoints:
- `/health`
- `/speech_to_text_health`
- `/speech_to_text`
- `/history`
- `/sfp`
- `/foul`

One-click launchers
-------------------
The project includes launcher scripts in the root folder.

Desktop web launcher:

```bash
NO_OPEN_BROWSER=1 ./launch_webpage.command desktop
```

Stop the launcher:

```bash
./launch_webpage.command stop
```

STT self-test:

```bash
./stt_selftest.sh
```

What the self-test checks:
- backend health
- STT health
- a temporary WAV sample posted to `/speech_to_text`

Mobile app
----------
The Flutter app is a translation client. It connects to the backend API and does not contain the STT feature anymore.

Run it from the mobile folder:

```bash
cd mobile
flutter pub get
flutter run
```

Useful backend address examples:
- Android emulator: `http://10.0.2.2:8000`
- iOS simulator: `http://127.0.0.1:8000`
- Physical device: use your Mac LAN IP, for example `http://192.168.x.x:8000`

Notes
-----
- Keep API keys out of the repository.
- Use `.streamlit/secrets.toml` or environment variables for secrets.
- Local learning data is stored in project files such as `user_feedback.csv`, `history.csv`, and model `.pkl` files.
- Retraining starts after at least 3 feedback entries.
- Use UTF-8 for Excel and text files so Cantonese characters display correctly.
- The web app can still use STT, but the mobile app no longer includes recording or speech-recognition UI.

Common troubleshooting
----------------------
- If Streamlit cannot import modules, check that you are running the project from the repository root and that the correct virtual environment is active.
- If backend startup fails, confirm port 8000 is free and that the project root is on `PYTHONPATH` when needed.
- If translation looks wrong, check the chosen API route, local dictionary match, and feedback history.

Project data
------------
Important files in the project root and backend data folder:
- `jyutping_dict.xlsx`
- `history.csv`
- `user_feedback.csv`
- `rf_model.pkl`
- `label_encoders.pkl`
- `backend/data/BACKGROUND.md`
- `backend/data/ACKNOWLEDGMENTS.md`

For more detailed usage examples, see `Q&A.txt`.