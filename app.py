"""Compatibility launcher.

Use `streamlit run streamlit_app.py` for the Streamlit UI.
This file remains as an entrypoint so existing commands still work.
"""

from webpage.streamlit_app import run_app


if __name__ == "__main__":
    run_app()
