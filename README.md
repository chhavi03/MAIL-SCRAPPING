# Mail Scrapping Project

This folder is a clean GitHub-ready copy of the project.

## Included files

- `main.py` - email order processor that extracts order data and submits it to a Google Form
- `automation_pyauto.py` - Google Form automation using `pyautogui`
- `automation_selenium.py` - Google Form automation using Selenium
- `test.py` - helper script for extracting order data and saving it to Excel
- `requirements.txt` - Python dependencies
- `.env.example` - environment variable template
- `.gitignore` - recommended Git ignore rules

## Setup

1. Create a virtual environment.
2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Create a `.env` file based on `.env.example`.
4. Add your own credentials and API key.

## Environment variables

```env
EMAIL_USER=your_email@example.com
EMAIL_PASS=your_app_password
GEMINI_API_KEY=your_gemini_api_key
```

## Run

Run any script you want, for example:

```powershell
python main.py
```

## Notes

- Do not upload your real `.env` file to GitHub.
- `venv`, `__pycache__`, and local runtime files are intentionally excluded.
- `processed_emails.txt` will be created automatically when needed.
