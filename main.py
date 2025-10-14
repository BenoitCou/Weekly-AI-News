import os
import json
import time
import sys
import re
import threading
from datetime import datetime, timezone, timedelta
from typing import List

from slack_sdk import WebClient
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from google import genai
from google.genai import types

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
MAIN_CHANNEL_ID = os.environ["MAIN_CHANNEL_ID"]
REVIEW_CHANNEL_ID = os.environ["REVIEW_CHANNEL_ID"]

date = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()

if not SLACK_BOT_TOKEN:
    raise RuntimeError("Missing SLACK_BOT_TOKEN in environment")
if not SLACK_APP_TOKEN:
    raise RuntimeError("Missing SLACK_APP_TOKEN (Socket Mode) in environment")
if not GEMINI_API_KEY:
    raise RuntimeError("Missing GEMINI_API_KEY in environment")

slack_client = WebClient(token=SLACK_BOT_TOKEN)
app = App(token=SLACK_BOT_TOKEN)

client = genai.Client(api_key=GEMINI_API_KEY)
GROUNDING_TOOL = types.Tool(google_search=types.GoogleSearch())

newsletter_sent = False
current_newsletter = None
handler = None                 
handler_thread = None          
stop_event = threading.Event() 


def send_to_main_channel(message: str):
    """Send newsletter to the main channel using blocks to preserve full content."""
    max_chunk_size = 2800
    message_chunks: List[str] = []

    if len(message) <= max_chunk_size:
        message_chunks = [message]
    else:
        paragraphs = message.split('\n\n')
        current_chunk = ""
        for paragraph in paragraphs:
            if len(current_chunk + paragraph + '\n\n') <= max_chunk_size:
                current_chunk += paragraph + '\n\n'
            else:
                if current_chunk:
                    message_chunks.append(current_chunk.strip())
                current_chunk = paragraph + '\n\n'
        if current_chunk:
            message_chunks.append(current_chunk.strip())

    blocks = []
    for chunk in message_chunks:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": chunk}
        })

    response = slack_client.chat_postMessage(
        channel=MAIN_CHANNEL_ID,
        blocks=blocks,
        text="AI Weekly Newsletter",
        unfurl_links=False,
        unfurl_media=False
    )
    print(f"Newsletter sent to main channel: {response['ts']}")
    return response['ts']


def send_to_review_channel(message: str):
    """
    Send newsletter to the review channel with Send/Regenerate buttons.
    Splits long content into multiple sections so Slack renders it safely.
    """
    max_chunk_size = 2800
    message_chunks: List[str] = []

    if len(message) <= max_chunk_size:
        message_chunks = [message]
    else:
        paragraphs = message.split('\n\n')
        current_chunk = ""
        for paragraph in paragraphs:
            if len(current_chunk + paragraph + '\n\n') <= max_chunk_size:
                current_chunk += paragraph + '\n\n'
            else:
                if current_chunk:
                    message_chunks.append(current_chunk.strip())
                current_chunk = paragraph + '\n\n'
        if current_chunk:
            message_chunks.append(current_chunk.strip())

    blocks = [{
        "type": "section",
        "text": {"type": "mrkdwn", "text": "*📋 Newsletter Review - Please choose an action:*"}
    }]

    for chunk in message_chunks:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": chunk}
        })

    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "✅ Send"},
                "style": "primary",
                "action_id": "send_newsletter",
                "value": "send"
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "🔄 Regenerate"},
                "action_id": "regenerate_newsletter",
                "value": "regenerate"
            }
        ]
    })

    response = slack_client.chat_postMessage(
        channel=REVIEW_CHANNEL_ID,
        blocks=blocks,
        text="Newsletter Review - Please choose an action",
        unfurl_links=False,
        unfurl_media=False
    )
    print(f"Review message sent to channel: {response['ts']}")
    return response['ts']


def generate_press_review():
    """
    Generates the weekly AI press review using Gemini with Google Search grounding.
    """
    system_instruction = (
        "You are a meticulous AI news editor. Always ground your output in Google Search results, "
        "include inline source links, and strictly avoid unverified claims. "
        "You ONLY use information from the most reputable newspapers and sources such as the Times, The Guardian, The Financial Times, "
        "The Daily Telegraph, The Independent, The New York Times, The Washington Post, The Wall Street Journal, Los Angeles Times, USA Today. "
        f"Ensure that all news items and sources are recent (after {date})."
    )

    user_prompt = (
        "Write a press review summarizing exactly 7 distinct AI news stories from this week "
        f"(only include events and articles published after {date}).\n\n"
        "Rules for content selection:\n"
        "2. The second news must cover *financial investments in AI*, which could be governmental or corportate investments, startup fundings, important mergers/acquisitions, etc.\n"
        "3. The third news must cover *public policy or regulations related to AI*.\n"
        "4. The last must be an *Chosen Story* that stimulates discussion by questioning assumptions—"
        "add one sentence explaining why you selected it. This story should be unique and distincitve. \n"
        "5. At least 1 news must focus on *AI in Europe*.\n"
        "6. At least 1 news must focus on *AI in Medicine & Healthcare*.\n"
        "7. The remaining news can cover other significant AI developments, such as research breakthroughs, applications in various sectors or interresting statements made by public figures about AI.\n"
        f"8. If you don't find relevant news for any of the above categories, you can replace it with another significant AI news story which occured after {date}.\n\n"
        "Formatting and style requirements:\n"
        f"• You always start you report with ' *AI WEEKLY REVIEW: AN OVERVIEW OF WHAT HAPPENED THIS WEEK ({date})* '.\n"
        "• Each news item must be exactly 3 sentences long.\n"
        "• Each item must cite mutliple reputable, recent sources with direct web links.\n"
        "• Reputable newspapers are the Times, The Guardian, The Financial Times, The Daily Telegraph, The Independent, The New York Times, The Washington Post, The Wall Street Journal, Los Angeles Times, USA Today.\n"
        "• Always use multiple reputable sources per item.\n"
        "• Use the exact format '\\n•*[Category of the news]* Title of the news' for each news headline.\n"
        "  Example categories: 'Investments', 'Public Policy', 'AI in Europe', "
        "'AI for Medicine & Healthcare', 'Research', 'AI for [specific sector]', 'Chosen Story'.\n\n"
        " for the Chosen Story only, add a sentence explaining why you selected it.\n\n"
        "Important: Do not add an introduction or conclusion. Start directly with the news list.\n\n"
        "Format to follow (output the exact same format, and only fill in the brackets):\n"
        f"*AI WEEKLY REVIEW: AN OVERVIEW OF WHAT HAPPENED THIS WEEK ({date})* \n\n"
        "• *Investments* [Title of the news]\n"
        "[3 sentences summarizing the news, with multiple inline source links]\n\n"
        "• *Public Policy & Regulations* [Title of the news]\n"
        "[3 sentences summarizing the news, with multiple inline source links]\n\n"
        "• *[Category]* [Title of the news]\n"
        "[3 sentences summarizing the news, with multiple inline source links]\n\n"
        "• *[Category]* [Title of the news]\n"
        "[3 sentences summarizing the news, with multiple inline source links]\n\n"
        "• *[Category]* [Title of the news]\n"
        "[3 sentences summarizing the news, with multiple inline source links]\n\n"
        "• *[Category]* [Title of the news]\n"
        "[3 sentences summarizing the news, with multiple inline source links]\n\n"
        "• *Chosen Story* [Title of the news]\n"
        "[3 sentences summarizing the news and one sentence explaining why you selected it, with multiple inline source links]. "
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=[GROUNDING_TOOL],
        temperature=1,
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=user_prompt,
        config=config,
    )
    return response


def create_dico(resp) -> dict:
    """
    Build {segment_text: [urls...]} dict from Gemini grounding metadata.
    """
    dico = {}
    supports = resp.candidates[0].grounding_metadata.grounding_supports
    chunks = resp.candidates[0].grounding_metadata.grounding_chunks
    for k in range(len(supports)):
        indices = supports[k].grounding_chunk_indices
        seg_text = supports[k].segment.text
        for i in indices:
            url = chunks[i].web.uri
            if seg_text not in dico:
                dico[seg_text] = [url]
            else:
                dico[seg_text].append(url)
    return dico


def add_slack_sources(text: str, mapping: dict) -> str:
    """
    For each supported segment sentence, append Slack-formatted [source] links.
    """
    for sentence, urls in mapping.items():
        if sentence in text:
            replaced = sentence
            for u in urls:
                replaced = f"{replaced} [<{u}|source>]"
            text = text.replace(sentence, replaced)
    return text


@app.action("send_newsletter")
def handle_send_newsletter(ack, body, client):
     """
        Handle the 'Send' button action for the newsletter.
     """ 
     global newsletter_sent, handler
     ack()
     
     if newsletter_sent:
         return
     
     newsletter_sent = True
     stop_event.set()
     print("Newsletter sent to main channel!")

     if current_newsletter:
         send_to_main_channel(current_newsletter)

     client.chat_update(
         channel=body["channel"]["id"],
         ts=body["message"]["ts"],
         text="✅ Newsletter sent to main channel!",
         blocks=[{
             "type": "section",
             "text": {"type": "mrkdwn", "text": "✅ *Newsletter sent to main channel!*"}
         }]
     )

@app.action("regenerate_newsletter")
def handle_regenerate_newsletter(ack, body, client):
    """    
    Handle the 'Regenerate' button action for the newsletter.
    """

    global newsletter_sent, current_newsletter
    ack()
    newsletter_sent = False
    print("Regeneration of the content...")

    client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        text="🔄 Regeneration ongoing...",
        blocks=[{
            "type": "section",
            "text": {"type": "mrkdwn", "text": "🔄 *Regeneration ongoing...*"}
        }]
    )

    try:
        resp = generate_press_review()
        text_body = resp.candidates[0].content.parts[0].text
        dico = create_dico(resp)
        current_newsletter = add_slack_sources(text_body, dico)
        send_to_review_channel(current_newsletter)
    except Exception as e:
        print(f"Erreur: {e}")
        client.chat_postMessage(
            channel=body["channel"]["id"],
            text=f"Error: {e}"
        )


def start_socket_handler_in_thread():
    """
    Start the Slack Socket Mode handler in a separate daemon thread.
    """
    global handler, handler_thread
    
    if handler is not None:
        return handler, handler_thread
        
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)

    def _run():
        try:
            handler.start()  # bloquant, mais dans un thread
        except Exception as e:
            print(f"[Socket thread] stopped with error: {e}")

    handler_thread = threading.Thread(target=_run, name="socket-mode-thread", daemon=True)
    handler_thread.start()
    return handler, handler_thread


def stop_socket_handler():
    """
    Stop the Slack Socket Mode handler and clean up resources.
    """
    global handler, handler_thread
    if handler is not None:
        try:
            handler.close()
            handler = None  
        except Exception as e:
            print(f"handler.close() failed: {e}")
    if handler_thread is not None:
        handler_thread.join(timeout=10)
        handler_thread = None  


def wait_for_send_button():
    """
    Wait for the 'Send' button to be pressed with timeout and logging.
    """
    
    print("Waiting for Send button to be pressed ...")
    start_socket_handler_in_thread()

    TIMEOUT_SECONDS = 2 * 60 * 60
    start_time = time.time()
    next_log_at = 0

    try:
        while True:
            if stop_event.is_set(): 
                print("✅ 'Send' pressed -> stopping handler.")
                break

            elapsed = time.time() - start_time
            remaining = TIMEOUT_SECONDS - elapsed

            if remaining <= 0:
                print("⏰ TIMEOUT: Program stopped after 2 hours.")
                stop_event.set()
                break

            if elapsed >= next_log_at:
                hrs = int(remaining // 3600)
                mins = int((remaining % 3600) // 60)
                print(f"⏰ Time remaining: {hrs}h {mins}m")
                next_log_at = elapsed + 300  

            stop_event.wait(timeout=1.0)

    except KeyboardInterrupt:
        print("Stopping by KeyboardInterrupt...")
    finally:
        stop_socket_handler()
        print("Socket handler stopped. Bye!")


if __name__ == "__main__":
    for attempts in range(3):
        try:
            resp = generate_press_review()
            text_body = resp.candidates[0].content.parts[0].text
            dico = create_dico(resp)
            current_newsletter = add_slack_sources(text_body, dico)
            print("Press review generated.\n")
            send_to_review_channel(current_newsletter)
            break
        except Exception as e:
            print(f"Startup generation failed: {e}")

    wait_for_send_button()

    print("Exiting now.")
