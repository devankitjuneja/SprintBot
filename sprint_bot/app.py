from fastapi import FastAPI, Request, Body
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
import json
from loguru import logger
from cachetools import TTLCache
import asyncio
import os
from sprint_bot.helpers import format_tickets_response, get_bot_capabilities_message
from sprint_bot.intent_recognition import detect_intent

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

event_cache = TTLCache(maxsize=1000, ttl=600)

# Slack and Zoho Sprints credentials
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
ZOHO_ACCESS_TOKEN = os.environ.get("ZOHO_ACCESS_TOKEN")
ZOHO_API_BASE_URL = "https://sprintsapi.zoho.com/zsapi"


def get_current_sprint():
    # Call Zoho Sprints API to fetch the current sprint
    logger.info(f"Fetching current sprint")
    response = requests.get(
        f"{ZOHO_API_BASE_URL}/team/669462816/projects/28091000000003109/sprints/",
        params={"action": "data", "index": 1, "range": 100, "type": "[2]"},
        headers={"Authorization": f"Bearer {ZOHO_ACCESS_TOKEN}"},
    )
    if response.status_code == 200:
        data = response.json()
        logger.info(f"Data: {data}")
        sprint_ids = data.get("sprintIds", [])
        if sprint_ids:
            return sprint_ids[0]  # Return the first sprint ID
        else:
            logger.info("No active sprints found.")
            return None
    else:
        logger.error(f"Failed to fetch sprints. Status code: {response.status_code}, Response: {response.text}")
        return None

def fetch_sprint_users():
    # Call Zoho Sprints API to fetch users in the current sprint
    logger.info(f"Fetching sprint users")
    team_id = "669462816"  # Replace with actual team ID
    sprint_id = get_current_sprint()

    response = requests.get(
        f"{ZOHO_API_BASE_URL}/team/{team_id}/projects/28091000000003109/sprints/{sprint_id}/users/",
        params={"action": "data", "index": 1, "range": 100},
        headers={"Authorization": f"Bearer {ZOHO_ACCESS_TOKEN}"},
    )
    # With the response, create a dictionary of user IDs and their display names
    if response.status_code == 200:
        data = response.json()
        logger.info(f"Data: {data}")
        users = data.get("userJObj", {})
        user_display_names = {}
        for user_id, user_info in users.items():
            user_display_names[user_id] = user_info[0]
        return user_display_names
    else:
        logger.error(f"Failed to fetch sprint users. Status code: {response.status_code}, Response: {response.text}")
        return None

def get_all_status():
    # Call Zoho Sprints API to fetch all status
    logger.info(f"Fetching all status")
    response = requests.get(
        f"{ZOHO_API_BASE_URL}/team/669462816/projects/28091000000003109/itemstatus/",
        params={"action": "data", "index": 1, "range": 100},
        headers={"Authorization": f"Bearer {ZOHO_ACCESS_TOKEN}"},
    )
    if response.status_code == 200:
        data = response.json()
        logger.info(f"Data: {data}")
        statuses = {}
        for status_id, status_info in data.get("statusJObj", {}).items():
            statuses[status_id] = status_info[0]  # status name is at index 0
        return statuses
    else:
        logger.error(f"Failed to fetch status. Status code: {response.status_code}, Response: {response.text}")
        return {}


def get_all_tickets():
    # Call Zoho Sprints API to fetch tickets assigned to the user
    team_id = "669462816"  # Replace with actual user ID
    sprint_id = get_current_sprint()
    sprint_users = fetch_sprint_users()
    statuses = get_all_status()
    print(sprint_users)
    logger.info(f"Fetching tickets for user")
    response = requests.get(
        f"{ZOHO_API_BASE_URL}/team/{team_id}/projects/28091000000003109/sprints/{sprint_id}/item/",
        params={"action": "data", "index": 1, "range": 100},
        headers={"Authorization": f"Bearer {ZOHO_ACCESS_TOKEN}"},
    )
    if response.status_code == 200:
        data = response.json()
        # logger.info(f"Data: {data}")
        tickets = data.get("itemJObj", {})
        user_display_names = data.get("userDisplayName", {})

        if tickets:
            raw_data = {
                "count": len(tickets),
                "tickets": []
            }
            for ticket_id, ticket_info in tickets.items():
                ticket = {
                    "id": ticket_id,
                    "title": ticket_info[0],
                    "status": statuses.get(ticket_info[26], "Unknown"),
                    "created_by": user_display_names.get(ticket_info[2], "Unknown"),
                    # assigned_to is now a dict: {user_id: user_display_name, ...}
                    "assigned_to": {user_id: user_display_names.get(user_id, "Unknown") for user_id in ticket_info[31]},
                }
                raw_data["tickets"].append(ticket)

            return raw_data
        else:
            logger.info("No tickets found.")
            return {"message": "No tickets found."}
    else:
        logger.error(f"Failed to fetch tickets. Status code: {response.status_code}, Response: {response.text}")
        return {"message": "Failed to fetch tickets."}

def get_tickets_for_user(user_id):
    """
    Returns tickets assigned to the given user_id.
    """
    all_tickets_data = get_all_tickets()
    if not all_tickets_data or "tickets" not in all_tickets_data:
        return {"count": 0, "tickets": []}

    filtered_tickets = []
    for ticket in all_tickets_data["tickets"]:
        # assigned_to is now a dict: {user_id: user_display_name, ...}
        if user_id in ticket.get("assigned_to", {}):
            filtered_tickets.append(ticket)

    return {
        "count": len(filtered_tickets),
        "tickets": filtered_tickets
    }

@app.get("/test")
async def test():
    # tickets = get_all_tickets()
    # Example usage for filtering by user_id:
    tickets = get_tickets_for_user("28091000000403001")
    return JSONResponse(content=tickets)

def send_slack_message(channel, text):
    response = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        json={"channel": channel, "text": text},
    )
    logger.info(f"Slack API response: {response.text}")


# Background task to process and send ticket results
async def handle_intent_in_background(user_id, channel, intent_result):
    final_message = "❌ Something went wrong while processing your request."
    try:
        if intent_result["intent"] == "get_my_tickets":
            tickets = get_tickets_for_user(user_id)
            if not tickets or not tickets.get("tickets"):
                final_message = "No tickets found assigned to you."
            else:
                final_message = format_tickets_response(tickets["tickets"])
        elif intent_result["intent"] == "create_ticket":
            final_message = create_ticket(
                title=intent_result.get("title", "Untitled Ticket"),
                assignee_name=intent_result.get("assignee"),
                user_id=user_id
            )
        elif intent_result["intent"] == "bot_capabilities":
            final_message = get_bot_capabilities_message()
        else:
            final_message = "❓ Sorry, I couldn't understand your request. Please rephrase or try another command."
    except Exception as e:
        logger.exception("Error handling intent in background")
        final_message = "❌ Something went wrong while processing your request."
    send_slack_message(channel, final_message)

# Endpoint to handle Slack events

@app.post("/slack/events")
async def slack_events(request: Request):
    data = await request.json()
    logger.info(f"Received Slack event: {data}")

    # Handle Slack URL verification (important to do before event cache check)
    if "challenge" in data:
        return JSONResponse(content={"challenge": data["challenge"]})

    event = data.get("event", {})
    event_id = data.get("event_id")

    # Only process message events that are not bot messages or edits
    if (
        event.get("type") == "message"
        and "subtype" not in event  # Ignore message_changed, message_deleted, etc.
        and not event.get("bot_id")  # Ignore messages sent by bots (including this bot)
    ):
        unique_event_id = event_id or event.get("event_ts")
        if unique_event_id in event_cache:
            logger.info(f"Duplicate event detected: {unique_event_id}")
            return JSONResponse(content={"status": "ok"}, status_code=200)

        event_cache[unique_event_id] = True

        user_message = event.get("text", "").lower()
        user_id = event.get("user")
        user_id = "28091000000403001"
        channel = event.get("channel")

        logger.info(f"Handling message from user {user_id}: {user_message}")

        intent_result = detect_intent(user_message)
        logger.info(f"Detected intent: {intent_result}")

        if intent_result:
            if intent_result["intent"] == "get_my_tickets":
                send_slack_message(channel, "🔍 Working on your request...")
                asyncio.create_task(handle_intent_in_background(user_id, channel, intent_result))
            elif intent_result["intent"] == "create_ticket":
                send_slack_message(channel, "📝 Creating your ticket...")
                asyncio.create_task(handle_intent_in_background(user_id, channel, intent_result))
            elif intent_result["intent"] == "bot_capabilities":
                send_slack_message(channel, "ℹ️ Listing my capabilities...")
                asyncio.create_task(handle_intent_in_background(user_id, channel, intent_result))
            else:
                send_slack_message(channel, "❓ Sorry, I couldn't understand your request. Please rephrase or try another command.")
        else:
            send_slack_message(channel, "❓ Sorry, I couldn't understand your request. Please rephrase or try another command.")

    return JSONResponse(content={"status": "ok"})

@app.post("/intent")
async def intent_router(payload: dict = Body(...)):
    """
    Accepts a JSON payload with a 'message' key, detects intent, and calls the respective function.
    Example payload: {"message": "Show me my tickets"}
    """
    message = payload.get("message", "")
    if not message:
        return JSONResponse(content={"error": "No message provided"}, status_code=400)

    intent = detect_intent(message)
    logger.info(f"Detected intent: {intent}")

    if intent == "get_my_tickets":
        # You may want to pass user_id from payload if needed
        # user_id = payload.get("user_id")
        # tickets = get_tickets_for_user(user_id) if user_id else get_all_tickets()
        tickets = get_tickets_for_user("28091000000403001")
        return JSONResponse(content=tickets)
    else:
        return JSONResponse(content={"error": "Intent not recognized or not supported."}, status_code=400)

def get_user_id_by_name(name, sprint_users):
    # Simple case-insensitive match for user display name
    for user_id, display_name in sprint_users.items():
        if display_name.lower() == name.lower():
            return user_id
    return None

def create_ticket(title, assignee_name=None, user_id=None):
    team_id = "669462816"
    project_id = "28091000000003109"
    sprint_id = get_current_sprint()
    sprint_users = fetch_sprint_users()
    # Default item type and priority (should be dynamic/configurable)
    projitemtypeid = "28091000000003133"
    projpriorityid = "28091000000003121"

    # Determine assignee user_id
    if assignee_name == "me" and user_id:
        assignee_id = user_id
    elif assignee_name:
        assignee_id = get_user_id_by_name(assignee_name, sprint_users)
    else:
        assignee_id = user_id

    users = [assignee_id] if assignee_id else []

    payload = {
        "name": title,
        "projitemtypeid": projitemtypeid,
        "projpriorityid": projpriorityid,
        "users": json.dumps(users),  # Ensure this is a JSON array string
        "description": ""
    }
    logger.info(f"Creating ticket with payload: {payload}")
    response = requests.post(
        f"{ZOHO_API_BASE_URL}/team/{team_id}/projects/{project_id}/sprints/{sprint_id}/item/",
        headers={"Authorization": f"Zoho-oauthtoken {ZOHO_ACCESS_TOKEN}"},
        data=payload,
    )
    if response.status_code in (200, 201):
        try:
            data = response.json()
            item_no = data.get("itemNo")
            if item_no:
                ticket_url = f"https://sprints.zoho.com/workspace/decisiontree#P2/itemdetails/{item_no}"
                final_message = f"✅ Ticket created successfully!\nTicket No: `{item_no}`\nURL: {ticket_url}"
            else:
                final_message = "✅ Ticket created, but could not fetch ticket ID."
        except Exception:
            final_message = "✅ Ticket created, but failed to parse response."
    else:
        logger.error(f"Failed to create ticket: {response.text}")
        final_message = "❌ Failed to create the ticket. Please try again."
    return final_message

# Start the FastAPI server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8080)
