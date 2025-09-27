import base64
# import markdown
import mistune
import json
import os
import time
from datetime import datetime
from typing import Dict, Optional
from dotenv import load_dotenv
from google.cloud import pubsub_v1
from supabase import create_client, Client
from gmail_utils import authenticate_gmail, setup_gmail_push_notifications

from database import DatabaseManager

# Rich imports - minimal set
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.markdown import Markdown
import re
from bs4 import BeautifulSoup

# Load environment variables
load_dotenv()

# Configuration
PROJECT_ID = os.getenv("PROJECT_ID", "")
SUBSCRIPTION_NAME = os.getenv("SUBSCRIPTION_NAME", "")
TOPIC_NAME = os.getenv("TOPIC_NAME", "")

# Initialize Rich Console
console = Console()

class GmailWorkflow:
    def __init__(self):
        """Initialize Gmail Workflow with essential clients"""
        self.service = authenticate_gmail()
        self.client = create_client(
            os.getenv("DATABASE_URL",""), 
            os.getenv("DATABASE_API_KEY","")
        )
        self.subscriber = pubsub_v1.SubscriberClient()
        self.subscription_path = self.subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_NAME)
        self.processed_messages = set()
        self.db = DatabaseManager(self.client)
        
        # Track conversations for display
        self.conversations = {}  # thread_id -> conversation history
        
        # Setup Gmail push notifications
        setup_gmail_push_notifications(self.service, PROJECT_ID, TOPIC_NAME)
        
        console.print("[green]✓[/green] Gmail Workflow Initialized - Rafael Email Agent ready")

    def display_conversation_header(self, user_email: str, thread_id: str):
        """Display conversation header with user info"""
        console.print(f"\n[bold white]User:[/bold white] {user_email} | [bold white]Thread:[/bold white] {thread_id}...")

    def display_rafael_message(self, message: str, title: str = "Rafael"):
        """Display Rafael's message in blue"""
        cleaned_message = self.clean_html_content(message)
        
        panel = Panel(
            Markdown(cleaned_message),
            title=f"[bold blue]{title}[/bold blue]",
            border_style="blue"
        )
        console.print(panel)
        console.print()  

    def display_user_message(self, message: str, title: str = "User Response"):
        """Display user's message in yellow"""
        cleaned_message = self.clean_html_content(message)
        
        panel = Panel(
            Markdown(cleaned_message),
            title=f"[bold yellow]{title}[/bold yellow]",
            border_style="yellow"
        )
        console.print(panel)
        console.print()  
        
    def clean_html_content(self, content: str) -> str:
        """Clean HTML content for terminal display"""
        import re
        
        # Remove HTML tags
        content = re.sub(r'<[^>]+>', '', content)
        
        # Decode HTML entities
        import html
        content = html.unescape(content)
        
        # Clean up extra whitespace
        content = re.sub(r'\n\s*\n', '\n\n', content)
        content = content.strip()
        
        return content

    def extract_user_email_from_thread(self, thread_id: str) -> str:
        """Extract user email from thread"""
        try:
            # Check if we have it cached
            if hasattr(self, 'active_threads') and thread_id in self.active_threads:
                return self.active_threads[thread_id].get('email', 'Unknown')
            
            # Try to get from thread messages
            thread = self.service.users().threads().get(userId='me', id=thread_id).execute()
            
            my_email = os.getenv("GMAIL_ADDRESS", "")
            if not my_email:
                profile = self.service.users().getProfile(userId='me').execute()
                my_email = profile.get('emailAddress', '')
            
            # Find first message not from us
            for message in thread['messages']:
                headers = message['payload'].get('headers', [])
                from_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
                if my_email.lower() not in from_header.lower():
                    # Extract email from header (handle "Name <email>" format)
                    import re
                    email_match = re.search(r'<([^>]+)>', from_header)
                    if email_match:
                        return email_match.group(1)
                    return from_header
            
            return "Unknown"
        except:
            return "Unknown"

    def send_initial_email(self, recipient: str, subject: str, body: str, name: str, raw_body: str) -> str:
        """Send first email and create workflow record"""
        # Use HTML content type and wrap body in HTML template for better formatting
        # Create email content with proper MIME structure
        email_content = [
            f"To: {recipient}",
            f"Subject: {subject}",
            "MIME-Version: 1.0",
            "Content-Type: text/html; charset=utf-8",
            "",  # Empty line separates headers from body
            f"<html><body style='font-family: Arial, sans-serif; font-size: 15px; color: #222;'>",
            body,  # Body already contains HTML from markdown conversion
            "</body></html>"
        ]
        
        # Join with proper line endings and encode
        message = {
            'raw': base64.urlsafe_b64encode(
                '\r\n'.join(email_content).encode('utf-8')
            ).decode()
        }
        
        # console.print(f"[dim]DEBUG: Starting send for {recipient} at {datetime.now()}[/dim]")
        
        # Add retry to handle rate limiting 
        max_retries = 3           
        try:
            for attempt in range(max_retries):
                try:
                    sent_message = self.service.users().messages().send(userId='me', body=message).execute()
                    # console.print(f"[dim]DEBUG: Gmail API call succeeded for {recipient} on attempt {attempt+1}[/dim]")
                    break  # Success, exit loop
                except Exception as e:
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt  # 1s, 2s, 4s
                        console.print(f"[yellow]Gmail send failed (attempt {attempt+1}): {e}. Retrying in {wait_time}s...[/yellow]")
                        time.sleep(wait_time)
                    else:
                        console.print(f"[red]Gmail send failed after {max_retries} attempts: {e}[/red]")
                        raise
            
            thread_id = sent_message['threadId']
            self.save_workflow_state(thread_id, step=0, status='sent_initial')
            
            # Display the conversation header
            self.display_conversation_header(recipient, thread_id)
            
            console.print(f"[dim]Initial email sent - Thread: {thread_id}[/dim]")
            
            # Add to Database
            
            # Create a dictionary to record message details
            message_dict = {
                "thread_id": thread_id,
                "message_id": sent_message['id'],
                "sender":"agent",
                "body": raw_body,
                "subject": subject,
                "timestamp": datetime.now().isoformat()
            }
            
            success, error = self.db.store_message({"email": recipient, "name": name}, message_dict)
            if not success:
                console.print(f"[red]DB store failed for {recipient}: {error}[/red]")
            # console.print(f"[dim]DEBUG: DB store completed for {recipient}[/dim]")
            
            
            return thread_id
            
        except Exception as e:
            console.print(f"[red]Error at {datetime.now()}: {e} (Type: {type(e).__name__})[/red]")
            raise

    
      

    def setup_enhanced_integration(self, chat_app=None, active_threads=None):
        """Setup integration with AI chat application and thread tracking"""
        if chat_app:
            self.chat_app = chat_app
        if active_threads is not None:
            self.active_threads = active_threads
        
        def enhanced_process_incoming_message(message: dict):
            try:
                # Debug: Check for required keys to prevent KeyError
                if 'threadId' not in message:
                    console.print(f"[yellow]Skipping message {message.get('id', 'unknown')} - missing threadId. Keys: {list(message.keys())}[/yellow]")
                    return
                
                if 'id' not in message:
                    console.print(f"[yellow]Skipping message - missing id. Keys: {list(message.keys())}[/yellow]")
                    return
                
                thread_id = message['threadId']
                message_id = message['id']
                
                my_email = os.getenv("GMAIL_ADDRESS", "")
                if not my_email:
                    profile = self.service.users().getProfile(userId='me').execute()
                    my_email = profile.get('emailAddress', '')
                
                # Skip if already processed
                if message_id in self.processed_messages:
                    return
                self.processed_messages.add(message_id)
                
                # Extract headers for validation
                headers = message['payload'].get('headers', [])
                from_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
                to_header = next((h['value'] for h in headers if h['name'].lower() == 'to'), '')
                
                # Pre-parse email from from_header to handle "Name <email>" format bug
                email_match = re.search(r'<([^>]+)>', from_header)
                user_email = email_match.group(1) if email_match else from_header
                
                # Extract email body
                email_body = self.extract_email_body(message)
                
                # Get user name from database
                try:
                    # Check if this is the agent's email
                    agent_email = os.getenv("GMAIL_ADDRESS", "")
                    if user_email == agent_email:
                        user_name = "Rafael"
                    else:
                        user_result = self.client.table('email_users').select('name').eq('email', user_email).execute()
                        if user_result.data:
                            user_name = user_result.data[0]['name']
                        else:
                            # Fallback to active threads data (from CSV)
                            user_name = self.active_threads.get(thread_id, {}).get('name', 'Unknown')
                    
                except Exception: 
                    user_name = self.active_threads.get(thread_id, {}).get('name', 'Unknown')
                
                # Add User Response to Database only for active threads
                if hasattr(self, 'active_threads') and thread_id in self.active_threads:
                    # Check whether from user or agent
                    sender_type = "agent" if my_email.lower() in from_header.lower() else "user"

                    message_dict = {
                        "thread_id": thread_id,
                        "message_id": message_id,
                        "sender": sender_type,
                        "body": email_body,
                        "subject": next((h['value'] for h in headers if h['name'].lower() == 'subject'), ''),
                        "timestamp": datetime.now().isoformat()
                    }
                
                    self.db.store_message({"email": user_email, "name": user_name}, message_dict)
                
                # Skip validation
                if my_email.lower() in from_header.lower():
                    return
                if my_email.lower() not in to_header.lower():
                    return
                if 'noreply' in from_header.lower():
                    return
                               
                # Load workflow state
                workflow_state = self.load_workflow_state(thread_id)
                if not workflow_state:
                    return
                    
                current_step = workflow_state['step']
                if current_step >= 4:
                    return
                
                # Display incoming user message
                console.print(Rule(style="white"))
                self.display_user_message(email_body, f"User Response #{current_step + 1}")
                
                # Generate AI response if chat app is available
                if hasattr(self, 'chat_app') and self.chat_app and hasattr(self, 'active_threads'):
                    user_email_from_threads = self.active_threads.get(thread_id, {}).get('email', '')
                    if user_email_from_threads:
                        try:
                            # Enhanced prompt with email content
                            base_prompts = {
                                0: f"The user {user_email_from_threads} has replied to our initial welcome email. Their response was: '{email_body[:500]}...' Generate a follow-up email asking more about their background and interests, acknowledging their previous response.",
                                1: f"The user {user_email_from_threads} has replied again. Their latest response was: '{email_body[:500]}...' Generate a more engaging follow-up email building on this conversation. The goal is to get to know them better.",
                                2: f"The user {user_email_from_threads} replied with: '{email_body[:500]}...' Based on their interests shown in this conversation, generate a personalized response incorporating our club's vision and mission. The goal is to know which events they would like. Do not recommend events. Do not hallucinate events; you are not aware of any upcoming events.",
                                3: f"Generate a final sending message for {user_email_from_threads} based on their response: '{email_body[:500]}...'. End the conversation politely and encourage them to reach out anytime. Do not suggest events. IMPORTANT: MUST include this exact ending note at the end of the email: 'This concludes our conversation with Rafael, the club agent. Feel free to reach out anytime.'"
                            }
                            
                            prompt = base_prompts.get(current_step, f"Generate a follow-up for {user_email_from_threads}")
                            # Retry AI response generation up to 3 times
                            max_ai_retries = 3
                            ai_response = None
                            for ai_attempt in range(max_ai_retries):
                                try:
                                    with console.status("[green]Generating response...[/green]", spinner="dots"):
                                        ai_response = self.chat_app.process_user_input(prompt)
                                    if ai_response:
                                        break  # Success, exit retry loop
                                except Exception:
                                    pass  # Silent retry
                            
                            # If all retries failed, use fallback
                            if not ai_response:
                                ai_response = "Thank you for your message! I'll prepare a more detailed response shortly."
                                                           
                            self.workflow_manager(thread_id, current_step, message, message_body=ai_response, name=user_name)
                            return
                        except Exception as e:
                            # Fall back to default workflow
                            pass
                
                # Use default workflow manager
                self.workflow_manager(thread_id, current_step, message)
                
            except Exception as e:
                console.print(f"[red]Error in enhanced message processing: {e}[/red]")
        
        # Replace the method
        self.process_incoming_message = enhanced_process_incoming_message

    def extract_email_body(self, message: dict) -> str:
        """Extract email body from Gmail message"""
        try:
            payload = message.get('payload', {})
            snippet = message.get('snippet', '')
            
            # Local helper to extract new content (removes quoted thread)
            def extract_new_content(text: str) -> str:
                lines = text.split('\n')
                new_content_lines = []
                for line in lines:
                    if (line.strip().startswith('From:') or 
                        line.strip().startswith('Sent:') or 
                        line.strip().startswith('To:') or
                        line.strip().startswith('Subject:') or
                        '________________________________' in line or
                        line.strip().startswith('>')):
                        break
                    new_content_lines.append(line)
                return '\n'.join(new_content_lines).strip()
            
            # Handle multipart messages
            if 'parts' in payload:
                for part in payload['parts']:
                    body_data = part.get('body', {}).get('data', '')
                    if not body_data:
                        continue
                    
                    decoded = base64.urlsafe_b64decode(body_data).decode('utf-8')
                    
                    if part.get('mimeType') == 'text/plain':
                        result = extract_new_content(decoded)
                        return result
                    
                    elif part.get('mimeType') == 'text/html':
                        try:
                            soup = BeautifulSoup(decoded, 'html.parser')
                            text = soup.get_text()
                            result = extract_new_content(text)
                            return result
                        except Exception:
                            pass
            
            # Handle single part messages
            body_data = payload.get('body', {}).get('data', '')
            if body_data:
                decoded = base64.urlsafe_b64decode(body_data).decode('utf-8')
                
                if payload.get('mimeType') == 'text/plain':
                    result = extract_new_content(decoded)
                    return result
                
                elif payload.get('mimeType') == 'text/html':
                    try:
                        soup = BeautifulSoup(decoded, 'html.parser')
                        text = soup.get_text()
                        result = extract_new_content(text)
                        return result
                    except Exception:
                        pass
            
            # Fallback to snippet
            return snippet
            
        except Exception:
            return message.get('snippet', '')


    def workflow_manager(self, thread_id: str, step: int, incoming_message: dict = {}, message_body: str = "", message_subject: str = "", name: str = "Unknown") -> None:
        """Enhanced workflow manager that supports AI-generated responses"""
        try:            
            if step <= 3:  # Changed from < 3 to <= 3 to include sending for step 3
                # Only send reply if we have a proper AI-generated response
                if message_body:

                    self.send_reply_email(thread_id, message_body, message_body=message_body, message_subject=message_subject, name=name)

                    # Display Rafael's response
                    self.display_rafael_message(message_body, f"Rafael - Follow-up #{step + 1}")
                    
                    if step == 3:
                        # For step 3, mark as completed after sending
                        self.save_workflow_state(thread_id, step=4, status='completed')
                        console.print(f"[green]✓ Conversation completed for thread {thread_id}...[/green]")
                    else:
                        self.save_workflow_state(thread_id, step=step+1, status=f'sent_followup_{step+1}')
                else:
                    # Mark as processed but don't advance step to avoid reprocessing
                    # self.save_workflow_state(thread_id, step=step, status=f'processed_no_response_{step}')
                    console.print(f"[yellow]⚠ Skipped reply for thread {thread_id}... - No AI response available[/yellow]")
            

        except Exception as e:
            console.print(f"[red]Error in workflow_manager: {e}[/red]")
            
    def fix_inline_bullets(self, text: str) -> str:
        """Robustly convert any list-like text to strict markdown bullets."""
        import re
        lines = text.split('\n')
        new_lines = []
        
        for line in lines:
            # Check if line has multiple dashes or starts with text followed by dash
            if re.search(r'\w.*-\s+\w', line) and '- ' in line:
                # Split on dashes, assuming the first part is intro
                parts = re.split(r'\s*-\s+', line)
                intro = parts[0].strip().rstrip(':').strip()  # Remove trailing colon
                bullets = [p.strip() for p in parts[1:] if p.strip()]
                if intro:
                    new_lines.append(intro)
                for bullet in bullets:
                    new_lines.append(f'- {bullet}')
            else:
                new_lines.append(line)
        
        return '\n'.join(new_lines)

    def send_reply_email(self, thread_id: str, body: str, message_body: str = "", message_subject: str = "", name: str = "Unknown") -> None:
        """Send reply in existing thread using HTML formatting"""
        try:
            # Get thread messages
            thread = self.service.users().threads().get(
                userId='me',
                id=thread_id
            ).execute()

            # Find most recent external message to reply to
            my_email = os.getenv("GMAIL_ADDRESS", "")
            if not my_email:
                profile = self.service.users().getProfile(userId='me').execute()
                my_email = profile.get('emailAddress', '')

            latest_external_message = None
            for message in reversed(thread['messages']):
                headers = message['payload'].get('headers', [])
                from_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
                if my_email.lower() not in from_header.lower():
                    latest_external_message = message
                    break

            if not latest_external_message:
                return

            headers = latest_external_message['payload'].get('headers', [])
            from_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
            subject_header = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
            message_id_header = next((h['value'] for h in headers if h['name'].lower() == 'message-id'), '')

            # Prepare reply subject
            if message_subject:
                reply_subject = message_subject
            else:
                reply_subject = f"Re: {subject_header}" if not subject_header.startswith('Re:') else subject_header

            # Use custom body
            email_body = message_body or body
            
            # Pre-process inline dashes to proper markdown lists 
            email_body = self.fix_inline_bullets(email_body)

            # Convert markdown to HTML
            # html_content = markdown.markdown(
            #     email_body.strip(),
            #     output_format='html',
            #     extensions=['extra', 'smarty']
            # )
            renderer = mistune.HTMLRenderer()
            markdown_parser = mistune.Markdown(renderer)
            html_content = markdown_parser(email_body.strip())

            # Wrap in div for consistent style and full HTML structure
            html_body = f"""
<html>
  <body style=\"font-family: Arial, sans-serif; font-size: 15px; color: #222;\">
    {html_content}
  </body>
</html>
"""

            # Create reply message with HTML content type
            reply_message = {
                'raw': base64.urlsafe_b64encode(
                    f"To: {from_header}\r\n"
                    f"Subject: {reply_subject}\r\n"
                    f"In-Reply-To: {message_id_header}\r\n"
                    f"References: {message_id_header}\r\n"
                    f"Content-Type: text/html; charset=utf-8\r\n"
                    f"\r\n{html_body}".encode('utf-8')
                ).decode(),
                'threadId': thread_id
            }

            # Send reply

            # Send reply with retry logic
            max_retries = 3
            try:
                for attempt in range(max_retries):
                    try:
                        reply_response = self.service.users().messages().send(userId='me', body=reply_message).execute()
                        console.print(f"[dim]DEBUG: Gmail API call succeeded for reply on attempt {attempt+1}[/dim]")
                        # Adding 3 second delay to ensure full processing
                        time.sleep(3)
                        break  # Success, exit loop
                    except Exception as e:
                        if attempt < max_retries - 1:
                            wait_time = 2 ** attempt  # 1s, 2s, 4s
                            console.print(f"[yellow]Gmail reply send failed (attempt {attempt+1}): {e}. Retrying in {wait_time}s...[/yellow]")
                            time.sleep(wait_time)
                        else:
                            console.print(f"[red]Gmail reply send failed after {max_retries} attempts: {e}[/red]")
                            raise
            except Exception as e:
                console.print(f"[red]Error sending reply: {e}[/red]")
                return  # Exit early if all retries failed

            # Parse email from from_header to handle "Name <email>" format bug
            email_match = re.search(r'<([^>]+)>', from_header)
            user_email = email_match.group(1) if email_match else from_header
            

            # Store Response in Database
            message_dict = {
                "thread_id": thread_id,
                "message_id": reply_response['id'],  # From Gmail API
                "sender": "agent",
                "body": email_body,  # The formatted reply body
                "subject": reply_subject,
                "timestamp": datetime.now().isoformat()
            }
            self.db.store_message({"email": user_email, "name": name}, message_dict)

        except Exception as e:
            console.print(f"[red]Error sending reply: {e}[/red]")

            
    def save_workflow_state(self, thread_id: str, step: int, status: str) -> None:
        """Save workflow state to Supabase"""
        try:
            workflow_data = {
                'thread_id': thread_id,
                'step': step,
                'status': status,
                'updated_at': datetime.now().isoformat()
            }
            
            self.client.table('email_workflow').upsert(
                workflow_data,
                on_conflict='thread_id'
            ).execute()
            
        except Exception as e:
            console.print(f"[red]Error saving workflow state: {e}[/red]")

    def load_workflow_state(self, thread_id: str) -> Optional[Dict]:
        """Load workflow state from Supabase"""
        try:
            result = self.client.table('email_workflow').select('*').eq('thread_id', thread_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            console.print(f"[red]Error loading workflow state: {e}[/red]")
            return None

    def start_listening(self):
        """Start Pub/Sub listener"""
        def callback(message):
            try:
                self.pubsub_listener(message.data)
                message.ack()
            except Exception as e:
                if "timed out" not in str(e).lower():
                    console.print(f"[red]Error processing Pub/Sub message: {e}[/red]")
                message.ack()
        
        # Configure flow control
        flow_control = pubsub_v1.types.FlowControl(max_messages=10)
        future = self.subscriber.subscribe(
            self.subscription_path, 
            callback=callback,
            flow_control=flow_control
        )

        return future

    def stop_listening(self, future):
        """Stop Pub/Sub listener"""
        if future:
            future.cancel()

    def pubsub_listener(self, event_data: bytes) -> None:
        """Pub/Sub listener for Gmail notifications"""
        try:
            notification = json.loads(event_data.decode('utf-8'))
            history_id = notification.get('historyId')
            
            if not history_id:
                return
            
            # Try history API first, fallback to recent messages
            messages_to_process = []
            
            try:
                history_response = self.service.users().history().list(
                    userId='me',
                    startHistoryId=str(max(1, int(history_id) - 100)),
                    historyTypes=['messageAdded']
                ).execute()
                
                # Extract messages from history
                for history_item in history_response.get('history', []):
                    for message_added in history_item.get('messagesAdded', []):
                        messages_to_process.append(message_added['message']['id'])
                        
            except Exception:
                # Fallback: get recent messages
                try:
                    recent_messages = self.service.users().messages().list(
                        userId='me', maxResults=5
                    ).execute()
                    
                    messages_to_process = [msg['id'] for msg in recent_messages.get('messages', [])]
                except Exception:
                    return
            
            # Process each message
            for message_id in messages_to_process:
                try:
                    full_message = self.service.users().messages().get(
                        userId='me', id=message_id, format='full'
                    ).execute()
                    
                    self.process_incoming_message(full_message)
                except Exception:
                    continue  # Silently skip failed messages
                    
        except Exception:
            pass  # Silently handle all errors including timeout