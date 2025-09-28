# Coffee Chat Booking Agent - Real Google APIs Implementation
# !pip install cohere google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client

import cohere
import os
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any
import base64
from email.mime.text import MIMEText
import pytz

# Google API imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# OAuth 2.0 scopes
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/gmail.send'
]

class GoogleAPIManager:
    def __init__(self, service_account_file=None):
        if service_account_file is None:
            service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service-account-key.json")
        self.service_account_file = service_account_file
        self.creds = self._authenticate()
        self.calendar_service = build('calendar', 'v3', credentials=self.creds)
        self.gmail_service = build('gmail', 'v1', credentials=self.creds)

    def _authenticate(self):
        from google.oauth2 import service_account
        
        scopes = [
            'https://www.googleapis.com/auth/calendar',
            'https://www.googleapis.com/auth/gmail.send'
        ]
        
        service_account_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if service_account_json:
            try:
                service_account_info = json.loads(service_account_json)
                creds = service_account.Credentials.from_service_account_info(
                    service_account_info, scopes=scopes)
                
                # Impersonate your workspace email
                impersonation_email = os.getenv("GOOGLE_IMPERSONATION_EMAIL", "vach@vachiverse.com")
                delegated_creds = creds.with_subject(impersonation_email)
                
                print("✅ Successfully authenticated with domain-wide delegation")
                return delegated_creds
            except Exception as e:
                print(f"❌ Domain-wide delegation error: {e}")
                raise
            
class CoffeeChatAgent:
    def __init__(self, cohere_api_key: str):
        self.co = cohere.Client(api_key=cohere_api_key)
        self.google_api = GoogleAPIManager()
        self.conversation_history = []
        self.tools = self._setup_tools()
        
    def _setup_tools(self):
        """Define the tools available to the agent"""
        return [
            {
                "name": "check_calendar_availability",
                "description": "Check Vach's calendar availability for the specified date range",
                "parameter_definitions": {
                    "date_range": {
                        "description": "Date range to check (e.g., 'next week', 'this Friday', 'January 15-20')",
                        "type": "str",
                        "required": True
                    },
                    "duration": {
                        "description": "Meeting duration in minutes (default: 30)",
                        "type": "int",
                        "required": False
                    }
                }
            },
            {
                "name": "create_google_meet_event",
                "description": "Create a Google Calendar event with Google Meet link",
                "parameter_definitions": {
                    "date": {
                        "description": "Meeting date in YYYY-MM-DD format",
                        "type": "str",
                        "required": True
                    },
                    "time": {
                        "description": "Meeting time in HH:MM format (24-hour)",
                        "type": "str",
                        "required": True
                    },
                    "duration": {
                        "description": "Meeting duration in minutes",
                        "type": "int",
                        "required": True
                    },
                    "attendee_email": {
                        "description": "Email address of the person booking the meeting",
                        "type": "str",
                        "required": True
                    },
                    "topic": {
                        "description": "Meeting topic or purpose",
                        "type": "str",
                        "required": False
                    }
                }
            },
            {
                "name": "send_confirmation_email",
                "description": "Send confirmation email to the attendee via Gmail",
                "parameter_definitions": {
                    "attendee_email": {
                        "description": "Email address of the attendee",
                        "type": "str",
                        "required": True
                    },
                    "event_details": {
                        "description": "JSON string containing meeting details",
                        "type": "str", 
                        "required": True
                    }
                }
            }
        ]

    def _parse_date_range(self, date_range: str) -> tuple:
        """Parse natural language date range into datetime objects"""
        now = datetime.now()
        
        if "next week" in date_range.lower():
            start = now + timedelta(days=(7 - now.weekday()))
            end = start + timedelta(days=7)
        elif "this week" in date_range.lower():
            start = now
            end = now + timedelta(days=(6 - now.weekday()))
        elif "tomorrow" in date_range.lower():
            start = now + timedelta(days=1)
            end = start + timedelta(days=1)
        else:
            # Default to next 7 days
            start = now
            end = now + timedelta(days=7)
        
        return start, end

    def list_available_calendars(self):
        """List all available calendars"""
        try:
            calendars_result = self.google_api.calendar_service.calendarList().list().execute()
            calendars = calendars_result.get('items', [])
            
            print("Available calendars:")
            for calendar in calendars:
                print(f"  - {calendar['summary']} (ID: {calendar['id']})")
                if calendar.get('primary'):
                    print(f"    ^ This is your PRIMARY calendar")
            
            return calendars
        except Exception as e:
            print(f"Error listing calendars: {e}")
            return []

        # Add this method to your agent class

    def check_calendar_availability(self, date_range: str, duration: int = 30) -> Dict:
        """Check real calendar availability using Google Calendar API"""
        try:
            print(f"🗓️  Checking calendar availability for: {date_range}")
            
            start_time, end_time = self._parse_date_range(date_range)
            
            # Query for busy times
            body = {
                "timeMin": start_time.isoformat() + 'Z',
                "timeMax": end_time.isoformat() + 'Z',
                "items": [{"id": os.getenv("CALENDAR_ID", "vachik123@gmail.com")}]
            }
            
            eventsResult = self.google_api.calendar_service.freebusy().query(body=body).execute()
            calendar_id = os.getenv("CALENDAR_ID", "vachik123@gmail.com")
            busy_times = eventsResult['calendars'][calendar_id]['busy']

            available_slots = []
            current_date = start_time.date()
            end_date = end_time.date()
            
            # Use Eastern timezone
            eastern = pytz.timezone('America/New_York')

            min_advance_hours = 24
            earliest_booking_time = datetime.now(eastern) + timedelta(hours=min_advance_hours)
    
            
            while current_date <= end_date:
                # Skip weekends
                if current_date.weekday() < 5:  # Monday = 0, Sunday = 6
                    # Check 9 AM to 9 PM in 30-minute intervals
                    for hour in range(9, 21):
                        for minute in [0, 30]:
                            # Create timezone-aware datetime for Eastern timezone
                            naive_dt = datetime.combine(current_date, datetime.min.time().replace(hour=hour, minute=minute))
                            slot_start = eastern.localize(naive_dt)
                            slot_end = slot_start + timedelta(minutes=duration)
                            
                            # Check if this slot conflicts with busy times
                            is_free = True
                            for busy in busy_times:
                                # Parse busy times (they come as UTC with 'Z' suffix)
                                busy_start_str = busy['start'].replace('Z', '+00:00')
                                busy_end_str = busy['end'].replace('Z', '+00:00')
                                busy_start = datetime.fromisoformat(busy_start_str)
                                busy_end = datetime.fromisoformat(busy_end_str)
                                
                                # Convert to Eastern timezone for comparison
                                busy_start = busy_start.astimezone(eastern)
                                busy_end = busy_end.astimezone(eastern)
                                
                                if (slot_start < busy_end and slot_end > busy_start):
                                    is_free = False
                                    break
                            
                            # Compare with current time (timezone-aware)
                            current_time = datetime.now(eastern)
                            if is_free and slot_start > earliest_booking_time:
                                available_slots.append({
                                    "date": current_date.strftime("%Y-%m-%d"),
                                    "time": slot_start.strftime("%H:%M"),
                                    "day": current_date.strftime("%A"),
                                    "formatted": slot_start.strftime("%A, %B %d at %I:%M %p EST")
                                })
                
                current_date += timedelta(days=1)
            
            # Limit to first 5 slots to avoid overwhelming the user
            available_slots = available_slots[:5]
            
            return {
                "available_slots": available_slots,
                "duration": duration,
                "timezone": "EST"
            }
            
        except HttpError as error:
            print(f"An error occurred: {error}")
            return {"error": f"Calendar check failed: {error}"}

    def create_google_meet_event(self, date: str, time: str, duration: int, 
                                attendee_email: str, topic: str = "Coffee Chat") -> Dict:
        """Create real Google Calendar event with Google Meet"""
        try:
            # Parse datetime
            event_datetime = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
            end_datetime = event_datetime + timedelta(minutes=duration)
            
            # Create event
            event = {
                'summary': f'Coffee Chat with Vach - {topic}',
                'description': f'Coffee chat discussion about: {topic}\n\nLooking forward to our conversation!',
                'start': {
                    'dateTime': event_datetime.isoformat(),
                    'timeZone': 'America/New_York',
                },
                'end': {
                    'dateTime': end_datetime.isoformat(),
                    'timeZone': 'America/New_York',
                },
                'attendees': [
                    {'email': attendee_email},
                ],
                'conferenceData': {
                    'createRequest': {
                        'requestId': f"meet_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                        'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                    }
                },
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'email', 'minutes': 60},
                        {'method': 'popup', 'minutes': 15},
                    ],
                },
            }
            
            # Create the event
            event_result = self.google_api.calendar_service.events().insert(
                calendarId='primary', 
                body=event,
                conferenceDataVersion=1,
                sendUpdates='all'
            ).execute()
            
            meet_link = None
            if 'conferenceData' in event_result and 'entryPoints' in event_result['conferenceData']:
                for entry_point in event_result['conferenceData']['entryPoints']:
                    if entry_point['entryPointType'] == 'video':
                        meet_link = entry_point['uri']
                        break
            
            print(f"📅 Created Google Calendar event:")
            print(f"   Event ID: {event_result['id']}")
            print(f"   Date: {date}")
            print(f"   Time: {time}")
            print(f"   Duration: {duration} minutes")
            print(f"   Attendee: {attendee_email}")
            print(f"   Topic: {topic}")
            print(f"   Meet Link: {meet_link}")
            
            return {
                "event_id": event_result['id'],
                "meet_link": meet_link,
                "calendar_link": event_result['htmlLink'],
                "date": date,
                "time": time,
                "duration": duration,
                "attendee": attendee_email,
                "topic": topic,
                "success": True
            }
            
        except HttpError as error:
            print(f"An error occurred: {error}")
            return {"error": f"Event creation failed: {error}", "success": False}

    def send_confirmation_email(self, attendee_email: str, event_details: str) -> Dict:
        """Send confirmation email to attendee AND notification email to Vach"""
        try:
            details = json.loads(event_details) if isinstance(event_details, str) else event_details
            
            # Format the time nicely
            event_time = datetime.strptime(f"{details['date']} {details['time']}", "%Y-%m-%d %H:%M")
            formatted_time = event_time.strftime("%A, %B %d at %I:%M %p EST")
            
            # Email 1: Confirmation to attendee
            attendee_content = f"""Hi there!

            This is an automated confirmation from Vach's booking system.

            Your coffee chat with Vach is confirmed:

            📅 When: {formatted_time}
            📹 Google Meet: {details.get('meet_link', 'Link will be in calendar invite')}
            💬 Topic: {details.get('topic', 'General chat')}
            📧 Calendar Invite: Sent to {attendee_email}

            I'm looking forward to our conversation!

            Best regards,
            Vach
            """
                    
            # Email 2: Notification to Vach
            notification_content = f"""New Coffee Chat Booking!

            Someone just booked a coffee chat with you:

            👤 Attendee: {attendee_email}
            📅 When: {formatted_time}
            📹 Google Meet: {details.get('meet_link', 'Link in calendar')}
            💬 Topic: {details.get('topic', 'General chat')}

            The calendar event has been created and confirmation sent to the attendee.

            ---
            Automated notification from your coffee chat booking system.
            """
        
            # Send to attendee
            attendee_message = MIMEText(attendee_content)
            attendee_message['to'] = attendee_email
            attendee_message['from'] = os.getenv("GMAIL_FROM_ADDRESS", "vach@vachiverse.com")
            attendee_message['subject'] = f'Coffee Chat Confirmed - {formatted_time}'
            
            attendee_raw = base64.urlsafe_b64encode(attendee_message.as_bytes()).decode()
            attendee_result = self.google_api.gmail_service.users().messages().send(
                userId='me',
                body={'raw': attendee_raw}
            ).execute()
            
            # Send notification to Vach
            notification_message = MIMEText(notification_content)
            notification_message['to'] = os.getenv("NOTIFICATION_EMAIL", "vachik123@gmail.com")
            notification_message['from'] = os.getenv("GMAIL_FROM_ADDRESS", "vach@vachiverse.com")
            notification_message['subject'] = f'New Booking: {formatted_time}'
            
            notification_raw = base64.urlsafe_b64encode(notification_message.as_bytes()).decode()
            notification_result = self.google_api.gmail_service.users().messages().send(
                userId='me',
                body={'raw': notification_raw}
            ).execute()
            
            print(f"📧 Confirmation email sent to: {attendee_email}")
            print(f"📧 Notification email sent to: {os.getenv('NOTIFICATION_EMAIL', 'vachik123@gmail.com')}")
            
            return {
                "success": True,
                "emails_sent": [attendee_email, os.getenv("NOTIFICATION_EMAIL", "vachik123@gmail.com")],
                "attendee_message_id": attendee_result['id'],
                "notification_message_id": notification_result['id'],
                "timestamp": datetime.now().isoformat()
            }
            
        except HttpError as error:
            print(f"An error occurred: {error}")
            return {"error": f"Email sending failed: {error}", "success": False}

    def execute_tool(self, tool_call):
        """Execute the appropriate tool based on the tool call"""
        tool_name = tool_call.name
        parameters = tool_call.parameters
        
        if tool_name == "check_calendar_availability":
            return self.check_calendar_availability(**parameters)
        elif tool_name == "create_google_meet_event":
            return self.create_google_meet_event(**parameters)
        elif tool_name == "send_confirmation_email":
            return self.send_confirmation_email(**parameters)
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    def chat(self, message: str, conversation_history: List = None):
        """Main chat interface with the agent"""
        if conversation_history is None:
            conversation_history = self.conversation_history

        preamble = """
        You are Vach's coffee chat booking assistant. You help people schedule 30-minute virtual coffee chats with Vach Melikian, a CS student at Rutgers who has experience in mobile development at Twitch and Fidelity.

        Your job is to:
        1. Understand what the person wants to discuss (career advice, technical questions, collaboration, etc.)
        2. Check Vach's real calendar availability using Google Calendar
        3. Help them pick a suitable time from available slots
        4. Create the Google Meet event in the calendar
        5. Send a professional confirmation email via Gmail

        Be friendly, professional, and helpful. Always ask for their email when you need to create the event.
        When showing available times, present them clearly and ask the user to pick one.
        """

        response = self.co.chat(
            model="command-r-08-2024",
            message=message,
            tools=self.tools,
            preamble=preamble,
            chat_history=conversation_history
        )

        # Handle tool calls
        while response.tool_calls:
            print(f"\n🤖 Agent wants to use tools: {[tc.name for tc in response.tool_calls]}")
            
            tool_results = []
            for tool_call in response.tool_calls:
                result = self.execute_tool(tool_call)
                tool_results.append({
                    "call": tool_call,
                    "outputs": [result]
                })

            # Continue conversation with tool results
            response = self.co.chat(
                model="command-r-08-2024",
                message="",
                tools=self.tools,
                chat_history=response.chat_history,
                tool_results=tool_results
            )

        # Update conversation history
        self.conversation_history = response.chat_history
        return response.text

# FastAPI Web Server Setup
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Coffee Chat Booking API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", 
        "https://coffee-chat-frontend-production.up.railway.app",
        "https://coffee-chat-agent-production.up.railway.app", 
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request/Response models
class ChatRequest(BaseModel):
    message: str
    conversation_id: str = None
    conversation_history: List = []

class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    conversation_history: List = []

# Endpoints
@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    try:
        print(f"📝 Received chat request: {request.message}")
        
        COHERE_API_KEY = os.getenv("COHERE_API_KEY")
        if not COHERE_API_KEY:
            print("❌ Missing COHERE_API_KEY")
            raise HTTPException(status_code=500, detail="Missing COHERE_API_KEY")
        
        print("✅ COHERE_API_KEY found")
        print(f"📊 Conversation history length: {len(request.conversation_history)}")
        
        agent = CoffeeChatAgent(COHERE_API_KEY)
        print("✅ Agent created successfully")
        
        response = agent.chat(request.message, request.conversation_history)
        print("✅ Agent chat completed")
        
        return ChatResponse(
            response=response,
            conversation_id=request.conversation_id or "default",
            conversation_history=agent.conversation_history
        )
    except Exception as e:
        print(f"❌ Chat endpoint error: {str(e)}")
        print(f"❌ Error type: {type(e)}")
        import traceback
        print(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/availability")
async def check_availability(date_range: str = "next week"):
    try:
        COHERE_API_KEY = os.getenv("COHERE_API_KEY")
        agent = CoffeeChatAgent(COHERE_API_KEY)
        return agent.check_calendar_availability(date_range)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/calendars")
async def list_calendars():
    try:
        COHERE_API_KEY = os.getenv("COHERE_API_KEY")
        agent = CoffeeChatAgent(COHERE_API_KEY)
        return {"calendars": agent.list_available_calendars()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "Coffee Chat Booking API"}

# Run the server
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)