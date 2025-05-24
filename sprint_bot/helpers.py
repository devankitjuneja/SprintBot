def format_tickets_response(tickets):
    if not tickets:
        return "No tickets assigned to you."

    message = "*🎟️ Your Tickets:*\n"
    for ticket in tickets:
        title = ticket["title"]
        status = ticket["status"]
        created_by = ticket["created_by"]
        message += f"\n• *{title}* _(Status: {status}, Created by: {created_by})_"

    return message

def get_bot_capabilities_message():
    return (
        "*🤖 Here are the tasks I can help you with:*\n\n"
        "1. *Get My Tickets*: Fetch all tickets assigned to you.\n"
        "   - _How to use_: \"Show me my tickets\", \"What tasks do I have assigned?\"\n"
        "   - _Requirements_: None.\n\n"
        "2. *Create Ticket*: Create a new ticket with a title and assignee.\n"
        "   - _How to use_: \"Add a new ticket titled 'Fix login bug' and assign it to Alice\", \"Add this to my tickets 'Modify warehouse layer'\"\n"
        "   - _Requirements_: You must specify the ticket title. Optionally, you can specify the assignee (e.g., a name or 'me').\n\n"
        "3. *Bot Capabilities*: List all tasks I can perform and their requirements.\n"
        "   - _How to use_: \"What can you do?\", \"Help\", \"List all features\"\n"
        "   - _Requirements_: None.\n"
    )