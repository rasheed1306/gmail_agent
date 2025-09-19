import base64
import markdown
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

    def send_initial_email(self, recipient: str, subject: str, body: str, name: str) -> str:
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
        
        try:
            sent_message = self.service.users().messages().send(
                userId='me', body=message
            ).execute()
            
            thread_id = sent_message['threadId']
            self.save_workflow_state(thread_id, step=0, status='sent_initial')
            
            # Display the conversation
            self.display_conversation_header(recipient, thread_id)
            self.display_rafael_message(body, "Rafael - Initial Email")
            
            console.print(f"[dim]Initial email sent - Thread: {thread_id}[/dim]")
            
            # Add to Database
            db = DatabaseManager(self.client)
            
            # Create a dictionary to record message details
            message_dict = {
                "thread_id": thread_id,
                "message_id": sent_message['id'],
                "sender":"agent",
                "body": body,
                "subject": subject,
                "timestamp": datetime.now().isoformat()
            }
            
            db.store_message({"email": recipient, "name": name}, message_dict)
            
            
            
            return thread_id
            
        except Exception as e:
            console.print(f"[red]✗ Error sending initial email: {e}[/red]")
            raise

    
      

    def setup_enhanced_integration(self, chat_app=None, active_threads=None):
        """Setup integration with AI chat application and thread tracking"""
        if chat_app:
            self.chat_app = chat_app
        if active_threads is not None:
            self.active_threads = active_threads
        
        def enhanced_process_incoming_message(message: dict):
            try:
                thread_id = message['threadId']
                message_id = message['id']
                
                # Skip if already processed
                if message_id in self.processed_messages:
                    return
                self.processed_messages.add(message_id)
                
                # Extract headers for validation
                headers = message['payload'].get('headers', [])
                from_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
                to_header = next((h['value'] for h in headers if h['name'].lower() == 'to'), '')
                
                # Extract email body
                email_body = self.extract_email_body(message)
                
                my_email = os.getenv("GMAIL_ADDRESS", "")
                if not my_email:
                    profile = self.service.users().getProfile(userId='me').execute()
                    my_email = profile.get('emailAddress', '')
                
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
                                0: f"The user {user_email_from_threads} has replied to our initial welcome email. Their response was: '{email_body[:500]}...' Generate a follow-up email asking about their background and interests, acknowledging their previous response.",
                                1: f"The user {user_email_from_threads} has replied again. Their latest response was: '{email_body[:500]}...' Generate a more engaging follow-up email building on this conversation.",
                                2: f"The user {user_email_from_threads} replied with: '{email_body[:500]}...' Based on their interests shown in this conversation, generate a personalized event invitation.",
                                3: f"Generate a final follow-up for {user_email_from_threads} based on their response: '{email_body[:500]}...'"
                            }
                            
                            prompt = base_prompts.get(current_step, f"Generate a follow-up for {user_email_from_threads}")
                            
                            ai_response = self.chat_app.process_user_input(prompt)
                            
                            self.workflow_manager(thread_id, current_step, message, message_body=ai_response)
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
            
            # Handle multipart messages
            if 'parts' in payload:
                for part in payload['parts']:
                    if part.get('mimeType') == 'text/plain':
                        body_data = part.get('body', {}).get('data', '')
                        if body_data:
                            decoded = base64.urlsafe_b64decode(body_data).decode('utf-8')
                            
                            # Extract only new content, remove quoted thread
                            lines = decoded.split('\n')
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
                            
                            result = '\n'.join(new_content_lines).strip()
                            return result
            
            # Handle single part messages
            elif payload.get('mimeType') == 'text/plain':
                body_data = payload.get('body', {}).get('data', '')
                if body_data:
                    decoded = base64.urlsafe_b64decode(body_data).decode('utf-8')
                    
                    # Extract only new content, remove quoted thread
                    lines = decoded.split('\n')
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
                    
                    result = '\n'.join(new_content_lines).strip()
                    return result
            
            # Fallback to snippet
            return message.get('snippet', '')
            
        except Exception as e:
            return message.get('snippet', '')

    def workflow_manager(self, thread_id: str, step: int, incoming_message: dict = {}, message_body: str = "", message_subject: str = "") -> None:
        """Enhanced workflow manager that supports AI-generated responses"""
        try:            
            if step < 3:  # Steps 0, 1, 2 send responses
                # Only send reply if we have a proper AI-generated response
                if message_body:
                    # Display Rafael's response
                    self.display_rafael_message(message_body, f"Rafael - Follow-up #{step + 1}")
                  
                    # Convert markdown to HTML before sending
                    html_body = markdown.markdown(
                        message_body.strip(),
                        output_format='html5',
                        extensions=['extra', 'smarty']
                    )
                    # Wrap in div for consistent style (optional)
                    html_body = f"<div style=\"font-family: Arial, sans-serif; line-height: 1.6; color: #333;\">{html_body}</div>"
                    print(f"🤖 DEBUG: Using HTML-converted body (length: {len(html_body)})")

                    subject = message_subject
                    self.send_reply_email(thread_id, message_body, message_body=message_body, message_subject=message_subject)
                    self.save_workflow_state(thread_id, step=step+1, status=f'sent_followup_{step+1}')
                else:
                    # Mark as processed but don't advance step to avoid reprocessing
                    # self.save_workflow_state(thread_id, step=step, status=f'processed_no_response_{step}')
                    console.print(f"[yellow]⚠ Skipped reply for thread {thread_id}... - No AI response available[/yellow]")
                
            elif step == 3:
                self.save_workflow_state(thread_id, step=4, status='completed')
                console.print(f"[green]✓ Conversation completed for thread {thread_id}...[/green]")
                
        except Exception as e:
            console.print(f"[red]Error in workflow_manager: {e}[/red]")

    def send_reply_email(self, thread_id: str, body: str, message_body: str = "", message_subject: str = "") -> None:
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

            # Use custom body if provided
            email_body = message_body or body

            # Format reply body with HTML paragraph breaks
            paragraphs = [p.strip() for p in email_body.strip().split('\n\n') if p.strip()]
            if not paragraphs:
                paragraphs = [email_body.strip()]
            body_paragraphs = [f"<p>{p}</p>" for p in paragraphs]
            formatted_html_body = '\n'.join(body_paragraphs)

            html_body = f"""
<html>
  <body style=\"font-family: Arial, sans-serif; font-size: 15px; color: #222;\">
    {formatted_html_body}
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
            self.service.users().messages().send(
                userId='me', body=reply_message
            ).execute()

            console.print(f"[dim]Reply sent - Thread: {thread_id[:12]}...[/dim]")
            console.print("[green]Workflow active - Rafael monitoring for incoming emails ...[/green]")
                
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
            
            self.client.table('workflows').upsert(
                workflow_data,
                on_conflict='thread_id'
            ).execute()
            
        except Exception as e:
            console.print(f"[red]Error saving workflow state: {e}[/red]")

    def load_workflow_state(self, thread_id: str) -> Optional[Dict]:
        """Load workflow state from Supabase"""
        try:
            result = self.client.table('workflows').select('*').eq('thread_id', thread_id).execute()
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