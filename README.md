# AI Weekly Slack Newsletter (Gemini + Socket Mode)

A Python app that generates a **weekly AI press review** with **Google Gemini** (grounded by Google Search) and posts it to Slack for **human-in-the-loop review**. Reviewers see the draft in a dedicated channel with **“Send”** and **“Regenerate”** buttons. On approval, the newsletter is posted to your main channel.

---

## Features

- **Exactly 7 news items**, each **3 sentences** with **multiple reputable sources** (NYT, FT, WSJ, Guardian, etc.)
- **Grounded with Google Search** via Gemini Tools; adds inline `[source]` links in Slack format
- **Reviewer flow** in Slack:
  - Draft posted to a **Review** channel with **Send** / **Regenerate** buttons
  - On **Send**, the approved content is posted to the **Main** channel
- **Safe message chunking** (≈2,800 chars) to avoid Slack truncation
- **Socket Mode** background listener with timeout & logs
- **Weekly execution of the code** with GitHub Actions
- **Gemini and GitHub Actions are free to run** for a reasonable daily/weekly usage

---

## Architecture

```
┌───────────────────────────┐
│  cron/manual run (python) │
└──────────────┬────────────┘
               │
      generate_press_review()
               │  (Gemini 2.5 Flash + Google Search Tool)
               ▼
        add_slack_sources()
               │
       send_to_review_channel()
               │
               ▼
     Slack (Review channel, buttons)
               │
   SocketModeHandler (actions)
     ┌─────────┴───────────┐
     │                     │
 "Send"                 "Regenerate"
     │                     │
 send_to_main_channel()    │
     │                     │
  Main channel             └─ regenerate via Gemini and repost draft
```

---

## Requirements

- **Python** 3.10+
- Slack workspace with permission to install a custom app
- **Google Gemini API** access and API key (free)
- Outbound internet access (to call Gemini)

---

## Environment variables

Create a `.env` file (or export these in your shell):

```env
# Slack
SLACK_BOT_TOKEN=xoxb-***
SLACK_APP_TOKEN=xapp-***        # Socket Mode token
MAIN_CHANNEL_ID=C123******      # Channel ID for final newsletter
REVIEW_CHANNEL_ID=U123******    # Channel ID for reviewer workflow

# Google Gemini
GEMINI_API_KEY=your_gemini_api_key
```

---

## Slack app configuration

1. **Create a Slack app** at api.slack.com/apps → "Create New App" → “From scratch”.
2. **Basic information → App-Level Tokens**: create one with scope `connections:write` (this generates your `SLACK_APP_TOKEN` starting with `xapp-`).
3. **OAuth & Permissions → Bot Token Scopes**: add at least:
   - `chat:write` (post messages)
   - `groups:read` (if posting to private channels)
4. **Install to Workspace** (generates `SLACK_BOT_TOKEN` starting with `xoxb-`).
5. **Socket Mode**: enable it.
6. **Interactivity & Shortcuts**: enable **Interactivity**.  
   (Socket Mode will receive the button actions; no public URL required.)
7. **Add the bot** to both the **Review** and **Main** channels (or the app won’t be able to post).

---

## Google Gemini setup

- Get an API key from Google AI Studio and set `GEMINI_API_KEY`.
- The code uses model: **`gemini-2.5-flash`** and enables **Google Search grounding**

---

## Running the code

```bash
git clone https://github.com/BenoitCou/Weekly-AI-News
cd Weekly-AI-News
pip install -r requirements.txt
python main.py
```

What happens:

1. On startup, the app attempts up to **3** generations with Gemini.
2. A **draft** is posted to the **Review** channel with **Send** / **Regenerate** buttons.
3. The app waits (up to **2 hours**) for a button action:
   - **Send** → posts the approved newsletter to **Main** channel and exits.
   - **Regenerate** → creates a fresh draft and re-posts to **Review**.
4. If no action is taken in 2 hours, the app times out and exits cleanly.

---

## Content rules (enforced by the prompt)

- Title format:
  ```
  *AI WEEKLY REVIEW: AN OVERVIEW OF WHAT HAPPENED THIS WEEK (<YYYY-MM-DD>)* 
  ```
- **Exactly 7 stories**, each **3 sentences**, with **multiple reputable sources** as inline links.
- Must include:
  - **Investments** story (funding/M&A/government/corporate)
  - **Public Policy & Regulations** story
  - At least **1 Europe** story
  - At least **1 Medicine & Healthcare** story
  - Final **Chosen Story** with an extra sentence explaining why it was selected
- Strictly **no introduction/conclusion** beyond the header.

The script post-processes Gemini’s grounded segments to append Slack `[source]` links.

---

## Configuration & customization

- **Date window**: by default, news must be **after `today-7 days`**.

- **Temperature** is set to 1 to ensure relevant news are chosen while keeping the LLM factual.

---


## Project structure

```
.
├──.github/workflows/press_review.yml        # the .yaml file handling the weekly execution of the code
├── main.py                                  # main script
└── requirements.txt                         # required libraries                                    
```

---

