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


def send_to_slack(message):
    response = slack_client.chat_postMessage(
            channel=SLACK_DM_ID,
            text=message,
            mrkdwn=True,
            unfurl_links=False,  
            unfurl_media=False   
        )
        
    print(f"Message sent on Slack : {response['ts']}")

def generate_press_review():
    system_instruction = (
        "You are a meticulous AI news editor. Always use Google Search grounding, "
        "include inline source links, and avoid unverified claims."
    )

    user_prompt = (
        f"Write a press review about the most important AI news of the current week."
        f"(news published after {date}). The review must include exactly 10 distinct news." 
        "At least 2 of them ones will focus on AI in Europe and at least 2 of them will be related to AI for Medicine & Healthcare.\n"
        "Each of those 10 news should be 2 sentences and MUST include a source web link."
        "Use multiple reputable sources per news. Use web search to find and verify the most important and recent facts." 
        "You'll use the format '\n•*Title*' for news titles."
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

def add_slack_sources(text: str, mapping: dict) -> str:
    for sentence, url in mapping.items():
        if sentence in text:
            for url in mapping[sentence]:
                replacement = f"{sentence} [<{url}|source>]"
                text = text.replace(sentence, replacement)
    return text

def create_dico(resp):
    dico = {}
    for k in range (0,len(resp.candidates[0].grounding_metadata.grounding_supports)):
        indices = resp.candidates[0].grounding_metadata.grounding_supports[k].grounding_chunk_indices
        for i in indices:
            if resp.candidates[0].grounding_metadata.grounding_supports[k].segment.text not in dico.keys():
                dico[resp.candidates[0].grounding_metadata.grounding_supports[k].segment.text] = [resp.candidates[0].grounding_metadata.grounding_chunks[i].web.uri]
            else :
                dico[resp.candidates[0].grounding_metadata.grounding_supports[k].segment.text].append(resp.candidates[0].grounding_metadata.grounding_chunks[i].web.uri)
    return dico

if __name__ == "__main__":
    resp = generate_press_review()
    text = resp.candidates[0].content.parts[0].text
    dico = create_dico(resp)
    print("Press review generated : \n\n", text)
    send_to_slack(add_slack_sources(text, dico)+"\n\n\n\n")
