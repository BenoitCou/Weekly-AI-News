import os
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv
import requests
from datetime import datetime, timezone, timedelta
from slack_sdk import WebClient
from google import genai
from google.genai import types
import re
from typing import List, Tuple

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_DM_ID = os.environ["SLACK_DM_ID"]

GROUNDING_TOOL = types.Tool(google_search=types.GoogleSearch())


date = (datetime.now(timezone.utc) - timedelta(days=5)).date().isoformat()

client = genai.Client(api_key=GEMINI_API_KEY) 
slack_client = WebClient(token=SLACK_BOT_TOKEN)

def generate_press_review():
    system_instruction = (
        "You are a meticulous AI news editor. Always use Google Search grounding, "
        "include inline source links, and avoid unverified claims."
    )

    user_prompt = (
        f"Write a press review about the most important AI news of the current week."
        f"(news published after {date}). The review must include exactly 10 distinct news." 
        "At least 2 of them ones will focus on AI in Europe and at least 2 of them will be related to AI for Medicine & Healthcare.\n"
        "Each of those 7 news should be 2 sentences and MUST include a source web link."
        "Only use reputable sources. Use web search to find and verify the most important and recent facts." 
        "You'll use the format '- *Title*' for news titles."
        f"You always start you report with '*AI WEEKLY REVIEW: AN OVERVIEW OF WHAT HAPPENED THIS WEEK ({date})*'."
        "You then directly give the news without any introduction."
    )


    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=[GROUNDING_TOOL],
        temperature=0.2,
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=user_prompt,
        config=config,
    )

    return response

def format_for_slack(response) -> str:
    def _get_text(cand) -> str:
        parts = []
        for p in getattr(cand.content, "parts", []) or []:
            if hasattr(p, "text") and p.text:
                parts.append(p.text)
        return "".join(parts)

    if not getattr(response, "candidates", None):
        return str(response)

    cand = response.candidates[0]
    text = _get_text(cand)

    gm = getattr(cand, "grounding_metadata", None)
    supports = getattr(gm, "grounding_supports", None)
    chunks = getattr(gm, "grounding_chunks", None)

    if not gm or not supports or not chunks:
        out = re.sub(r"^## (.*)", r"*\1*", text, flags=re.MULTILINE)
        out = re.sub(r"^### (.*)", r"*\1*", out, flags=re.MULTILINE)
        return out.strip()

    spans: List[Tuple[int, int, List[str]]] = []
    for sup in supports:
        seg = getattr(sup, "segment", None)
        if not seg:
            continue
        s, e = getattr(seg, "start_index", None), getattr(seg, "end_index", None)
        if not isinstance(s, int) or not isinstance(e, int):
            continue

        uris: List[str] = []
        for idx in getattr(sup, "grounding_chunk_indices", []) or []:
            if 0 <= idx < len(chunks):
                web = getattr(chunks[idx], "web", None)
                uri = getattr(web, "uri", None) if web else None
                if uri and uri not in uris:
                    uris.append(uri)

        if uris:
            spans.append((s, e, uris))

    if not spans:
        out = re.sub(r"^## (.*)", r"*\1*", text, flags=re.MULTILINE)
        out = re.sub(r"^### (.*)", r"*\1*", out, flags=re.MULTILINE)
        return out.strip()

    spans.sort(key=lambda x: (x[0], -(x[1]-x[0])))
    dedup: List[Tuple[int, int, List[str]]] = []
    for s, e, uris in spans:
        if dedup and s >= dedup[-1][0] and e <= dedup[-1][1]:
            continue
        dedup.append((s, e, uris))

    out = text
    for s, e, uris in sorted(dedup, key=lambda x: x[0], reverse=True):
        if not uris:
            continue
        url = uris[0]  
        e = max(0, min(e, len(out)))

        nl_idx = out.find("\n", e)
        line_end = len(out) if nl_idx == -1 else nl_idx

        insert_pos = line_end
        while insert_pos > 0 and out[insert_pos - 1] in " \t":
            insert_pos -= 1

        needs_space = True
        if insert_pos == 0 or out[insert_pos - 1] in " \t([{\"'":
            needs_space = False

        marker = f"{' ' if needs_space else ''}<{url}|[source]>"
        out = out[:insert_pos] + marker + out[insert_pos:]

    out = re.sub(r"^## (.*)", r"*\1*", out, flags=re.MULTILINE)
    out = re.sub(r"^### (.*)", r"*\1*", out, flags=re.MULTILINE)

    return out.strip()

def normalize_slack_bold_and_lists(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"^\*\s+", "- ", text, flags=re.MULTILINE)
    text = re.sub(r"^([*\-•])(\S)", r"\1 \2", text, flags=re.MULTILINE)
    return text

def send_to_slack(message):
    response = slack_client.chat_postMessage(
            channel=SLACK_DM_ID,
            text=message,
            mrkdwn=True,
            unfurl_links=False,  
            unfurl_media=False   
        )
        
    print(f"Message sent on Slack : {response['ts']}")

if __name__ == "__main__":
    resp = generate_press_review()
    md = format_for_slack(resp)
    md = normalize_slack_bold_and_lists(md)
    print("Press review generated : \n\n", md)
    send_to_slack(md+"\n\n\n\n")
