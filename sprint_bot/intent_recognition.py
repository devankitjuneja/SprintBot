from openai import OpenAI
import os
import dotenv
import re
from typing import Optional, Dict, Any
import json

dotenv.load_dotenv()


# Predefined intent
INTENTS = {
    "get_my_tickets": "Fetch all tickets assigned to the current user.",
    "create_ticket": "Create a new ticket with a title and optional assignee.",
    "bot_capabilities": "List all tasks the bot can perform and their requirements.",
    "delete_ticket": "Delete a ticket by its ticket ID.",
}

# Define prompt examples
FEW_SHOT_EXAMPLES = [
    {"query": "Show me my tickets", "intent": "get_my_tickets"},
    {"query": "What tasks do I have assigned?", "intent": "get_my_tickets"},
    {"query": "Add this to my tickets \"Modify warehouse layer\"", "intent": "create_ticket", "title": "Modify warehouse layer", "assignee": "me"},
    {"query": "Add a new ticket titled \"Modify code structure\" and assign it to Albert", "intent": "create_ticket", "title": "Modify code structure", "assignee": "Alice"},
    {"query": "Create a ticket called \"Fix login bug\"", "intent": "create_ticket", "title": "Fix login bug"},
    {"query": "Create a ticket in my bucket - Fix Login Bug", "intent": "create_ticket", "title": "Fix Login Bug", "assignee": "me"},
    {"query": "Create a ticket for 'Improve performance' and assign it to Alice", "intent": "create_ticket", "title": "Improve performance", "assignee": "Alice"},
    {"query": "What can you do?", "intent": "bot_capabilities"},
    {"query": "Help", "intent": "bot_capabilities"},
    {"query": "List all features", "intent": "bot_capabilities"},
    {"query": "Delete ticket I2378", "intent": "delete_ticket", "ticket_id": "I2378"},
    {"query": "Remove ticket with ID I2312", "intent": "delete_ticket", "ticket_id": "I2312"},
    {"query": "Delete the ticket I1212", "intent": "delete_ticket", "ticket_id": "I1212"},
]

def extract_title_and_assignee(query: str) -> Dict[str, Any]:
    # Try to extract title in quotes
    title_match = re.search(r"(?:titled|called|ticket|add|this to my tickets)[\s:]*[\"']([^\"']+)[\"']", query, re.IGNORECASE)
    if not title_match:
        title_match = re.search(r"[\"']([^\"']+)[\"']", query)
    title = title_match.group(1) if title_match else None

    # Try to extract assignee
    assignee_match = re.search(r"assign(?: it)? to ([\w\s]+)", query, re.IGNORECASE)
    if assignee_match:
        assignee = assignee_match.group(1).strip()
    elif "to my tickets" in query or "for me" in query or "assign to me" in query:
        assignee = "me"
    else:
        assignee = None

    return {"title": title, "assignee": assignee}

def extract_ticket_id(query: str) -> str:
    # Match patterns like 'I2378', 'ticket I2378', 'ticket no I2378', etc.
    match = re.search(r"(?:ticket(?:\s*with)?(?:\s*id)?\s*)?(I?\d+)", query, re.IGNORECASE)
    if match:
        ticket_id = match.group(1)
        # If it starts with 'I', strip it for internal use, but keep for item_no matching
        if ticket_id.upper().startswith('I'):
            return ticket_id.upper()
        return ticket_id
    return None

def detect_intent(query: str) -> Optional[Dict[str, Any]]:
    prompt = (
        "You are an assistant that classifies user queries into intents and extracts ticket title and assignee if present.\n"
        "Respond ONLY in valid JSON (double quotes, not single quotes) with keys: intent, title (if present), assignee (if present).\n"
        "Here are some examples:\n\n"
    )
    for ex in FEW_SHOT_EXAMPLES:
        example = {"intent": ex['intent']}
        if ex.get("title"):
            example["title"] = ex["title"]
        if ex.get("assignee"):
            example["assignee"] = ex["assignee"]
        prompt += f'User: {ex["query"]}\n{json.dumps(example)}\n\n'
    prompt += f'User: {query}\n'
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are an assistant that extracts intent, title, and assignee from user queries and always responds in valid JSON (double quotes, not single quotes)."},
            {"role": "user", "content": prompt}
        ],
        temperature=0,
        max_tokens=150,
        top_p=1.0,
        frequency_penalty=0.0,
        presence_penalty=0.0,
        stop=["\n", "User:", "Assistant:"]
    )
    content = response.choices[0].message.content.strip()

    try:
        if content.startswith("{") and content.endswith("}"):
            fixed_content = content.replace("'", '"')
            result = json.loads(fixed_content)
        else:
            result = json.loads(content)
        if "intent" in result:
            result["intent"] = result["intent"].lower()
        # For delete_ticket, ensure ticket_id is present
        if result.get("intent") == "delete_ticket" and not result.get("ticket_id"):
            ticket_id = extract_ticket_id(query)
            if ticket_id:
                result["ticket_id"] = ticket_id
        return result
    except Exception:
        pass
    try:
        # Fallback to previous regex-based extraction if not valid JSON
        intent_match = re.search(r"Intent:\s*([^\n]+)", content, re.IGNORECASE)
        title_match = re.search(r"Title:\s*([^\n]+)", content, re.IGNORECASE)
        assignee_match = re.search(r"Assignee:\s*([^\n]+)", content, re.IGNORECASE)
        ticket_id_match = re.search(r"ticket_id\s*[:=]\s*(I?\d+)", content, re.IGNORECASE)
        intent = intent_match.group(1).strip() if intent_match else None
        title = title_match.group(1).strip() if title_match else None
        assignee = assignee_match.group(1).strip() if assignee_match else None
        ticket_id = ticket_id_match.group(1) if ticket_id_match else extract_ticket_id(query)
        if (intent and intent.lower() == "create_ticket") and (not title or not assignee):
            extracted = extract_title_and_assignee(query)
            title = title or extracted["title"]
            assignee = assignee or extracted["assignee"]
        if intent and intent.lower() in {k.lower() for k in INTENTS}:
            result = {"intent": intent.lower()}
            if title:
                result["title"] = title
            if assignee:
                result["assignee"] = assignee
            if intent.lower() == "delete_ticket" and ticket_id:
                result["ticket_id"] = ticket_id
            return result
    except Exception:
        pass
    return None

if __name__ == "__main__":
    message = "Delete ticket with ID I2378"
    print(detect_intent(message))
    # message = 'Create a ticket called "Fix login bug" and assign it to me'
    # print(detect_intent(message))
