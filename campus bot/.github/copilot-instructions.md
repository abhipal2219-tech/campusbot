# GitHub Copilot Instructions for "campus bot"

This repository is very small and consists of two Python scripts: `bot.py` and `flask.py`.
The primary purpose is educational/demonstration of a simple mentor lookup bot using the
Google Generative AI SDK and a trivial Flask web server.

## High‑Level Overview

- **`bot.py`**: A command‑line chat program.  It configures the `google.generativeai` SDK
  with a hard‑coded API key and uses a `mentor_data` string as the system prompt.
  The chat loop reads from `input()` and prints responses.  There is no packaging,
  no tests, and no persistence.

- **`flask.py`**: A minimal Flask application with one route (`/`) that replies with a
  "Hello, World!" HTML page.  It is intended to be run directly (`python flask.py`) with
  `debug=True`.

There are no additional modules, no dependencies beyond those imported at the top of
these files.

## Important Details & Conventions

- **API Key Handling**:  `bot.py` currently embeds the API key directly in source:
  ``genai.configure(api_key="AIzaSyDKHkrRJgOB6r38mswAPX4KDXE5iBNRO10")``.  This is
  obviously insecure; if you make modifications, switch to reading from an environment
  variable or other secret store.  Tools that generate code should avoid leaking
  keys and may remove or replace this line with `os.environ.get("API_KEY")`.

- **Mentor Data Format**:  The lookup table is a plain text triple‑quoted string.  New
  sections are added by appending text.  Code that manipulates or validates this data
  should operate on a multi‑line string; there is no JSON/CSV parsing logic today.

- **Chat Model Configuration**:  The system instruction is built by concatenating the
  `mentor_data` string with additional text.  When modifying the prompt or model name,
  keep this pattern so that the chat initialization is clear:
  ```python
  model = genai.GenerativeModel(
      model_name="gemini-1.5-flash",
      system_instruction=f"System Context: {mentor_data}\n\nInstructions: ..."
  )
  ```

- **Interactive Loop**:  The loop in `bot.py` uses a simple `while True` with an exit
  condition of `exit` or `quit`.  New features (e.g., asynchronous calls) should preserve
  the `chat.send_message()` usage and `response.text` access.

- **Flask App**:  No blueprint structure, just a top‑level app.  Add routes directly to
  `app`.  The `if __name__ == "__main__"` guard is used to start the server in debug mode.

## Developer Workflows

- **Running the bot**:  ```powershell
  python bot.py
  ```
  The program immediately prompts for section/roll number input.  No virtual environment
  or build step is required; just install dependencies with `pip install google-generativeai`
  if they are missing.

- **Running the web server**:  ```powershell
  python flask.py
  ```
  Visit `http://127.0.0.1:5000/` in a browser to see the static page.

- **Dependencies**:  Only the `google-generativeai` package is explicitly required.  There
  is no `requirements.txt`; feel free to create one if you later install more packages.

- **Testing / linting**:  None present.  You can add unit tests using `pytest` if needed but
  there is no existing test harness to follow.  Code generation by Copilot should assume
  minimal structure and may suggest creating tests from scratch.

## Patterns & Conventions

- **No configuration files**:  Everything is hard‑coded.  When generating new features,
  avoid adding extraneous config files unless absolutely necessary; the current style is
  "single‑file, self‑contained".

- **No package or module namespaces**:  Both scripts are executed directly and are not
  imported from elsewhere.  If adding shared utilities, you may need to refactor into a
  module and update imports accordingly – note that currently there are none.

- **Simple string handling**:  The project avoids complex data structures.  Keep new code
  straightforward and readable.

## Integration & Dependencies

- **External API**:  The only external integration is the Google Generative AI service via
  `genai` client.  No other web services or databases are used.

- **No CI/CD or GitHub Actions**:  There are no workflows defined.  You may add them
  later, but an AI agent should not assume any automation exists.

## Notes for AI Agents

1. **Search scope**: Only two Python files exist.  Use `grep` or `file_search` if uncertain,
   but expect minimal complexity.  There are no tests, no packages, and no scripts.
2. **Editing tips**: Keep modifications concise and consistent with the one‑module style.
3. **Secrets**: Be cautious of the API key; do not expose real credentials in outputs.
4. **Extension guidance**: If asked to expand functionality (e.g. add new routes or
   convert mentor data to JSON), assume you may have to create new files but try to
   mirror the existing simplicity.

---

> 💡 _If any section above seems unclear or you need instructions for additional
> patterns not yet covered, please let me know so I can refine this guidance._
