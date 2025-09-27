from chat_manager import ChatApplication
import markdown
import dotenv
import os 
from supabase import create_client, Client
from sample_response import User_1, User_2
from LLM_Extraction import extract_member_info_llm
import pathlib
from gmail_utils import *
import asyncio
import json
import time
from datetime import datetime
from google_cloud import GmailWorkflow
import csv
import re
import mistune


# Rich imports
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.markdown import Markdown



# Initialize Rich Console
console = Console()

# System message that defines Rafael's persona and behavior as RAID's AI agent
system_message = """
You are Rafael, RAID's latest agent for the University of Melbourne's RAID (Responsive AI Development) club. Your task is to manage the email correspondence with a new member. Your primary goal is to initiate and maintain a conversation to build rapport, leading to a personalized invitation to club events.
Persona & Style: Write in a friendly, smart-casual, and conversational tone. The email must be easy to read and designed for a back-and-forth exchange.
Content and Structure: 
Initial Email: Draft a welcome email to a new member. Start with a warm greeting, introduce yourself as RAID's latest agent, and ask them about their interests and major. Do not provide any event details or recommendations; the goal is to encourage a reply and gather more information so that we can cater better events.
Subsequent Emails: Continue the conversation by asking follow-up questions about their background, interests, and experiences. Focus on building rapport and understanding their perspective. Do not mention, invent, or discuss any events, workshops, or club activities. Keep responses engaging and question-based to prompt replies.

IMPORTANT: Output ONLY the final email body. Do not include reasoning, drafts, checklists, mental sandbox, or any internal thoughts. Keep it clean and conversational.


MANDATORY FORMATTING RULES (Follow These Exactly for Proper HTML Conversion):
- Use **bold** for emphasis (e.g., "I'm **Rafael**, RAID's latest agent")
- Use *italics* for subtle emphasis (e.g., "Our *exciting* upcoming workshop")
- Use bullet points SPARINGLY for lists ONLY when it improves clarity (e.g., for multiple options or questions). Start EACH bullet on a NEW LINE with a single - followed by a space (e.g., - Item here). Avoid bullet points for simple lists or single items.
- Use proper paragraphs with blank lines between them
- Add ## for subheadings if needed
- Ensure ALL lists are valid markdown: No extra characters, no indentation issues, and each item on its own line. This ensures they convert to HTML <ul><li> tags correctly.

Example of properly formatted response: (do NOT copy this verbatim, just use as a style guide)
```
Hey there!

I'm **Rafael**, RAID's latest agent here at the *University of Melbourne*. It's great to have you join our community!

I noticed you're interested in AI and wanted to learn more about:
- Your current major
- What aspects of AI interest you most
- Any previous experience with AI/ML

Looking forward to your response!

Best,
Rafael
```

Constraints: Do not ask for any more information than what is specified above. The entire response should be under 250 words and ready to be used as a final output.
"""
root_dir = pathlib.Path(__file__).parent.parent
dotenv.load_dotenv(root_dir / ".env")

class IntegratedWorkflow:
    
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
    
    def format_email_body(self, raw_body: str) -> str:
        """
        Post-processes the LLM output to format the email body with HTML tags for greeting, paragraphs, and signature.
        Removes markdown code block wrappers (```html ... ``` or ``` ... ```).
        Converts markdown in the LLM output to HTML for email.
        """
        cleaned = raw_body.strip()
        if cleaned.startswith('```html') and cleaned.endswith('```'):
            cleaned = cleaned[7:-3].strip()
        elif cleaned.startswith('```') and cleaned.endswith('```'):
            cleaned = cleaned[3:-3].strip()
            # print("DEBUG - Removed code block wrapper")
            
        # print(f"DEBUG - Before markdown conversion: {cleaned}")
        
        # Pre-process inline dashes to proper markdown lists
        cleaned = self.fix_inline_bullets(cleaned)
        try:
            # Convert markdown to HTML
            # html_body = markdown.markdown(
            #     cleaned,
            #     output_format='html',
            #     extensions=['extra', 'smarty']
            # )
            
            renderer = mistune.HTMLRenderer()
            markdown_parser = mistune.Markdown(renderer)
            html_body = markdown_parser(cleaned)
            # print(f"DEBUG - Successfully converted to HTML: {html_body}")
            
            # Wrap in proper HTML structure
            html_output = f"""
<div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
{html_body}
</div>
""".strip()
            
            return html_output
            
        except Exception as e:
            # print(f"DEBUG - Error in markdown conversion: {str(e)}")
            return cleaned  # Fallback to cleaned text if conversion fails
    
    def __init__(self):
        """Initialize the integrated workflow system"""
        
        self.workflow = GmailWorkflow()
        self.chat_app = None
        self.supabase = create_client(os.getenv("DATABASE_URL", ""), os.getenv("DATABASE_API_KEY", ""))
        self.active_threads = {}  # Track active conversation threads
        
        console.print("[green]✓[/green] Workflow components initialized")
        
    def setup_chat_application(self):
        """Setup the chat application with enhanced context"""
        with console.status("[yellow]Setting up AI chat application...", spinner="dots"):
            context = self.read_files_content()
            enhanced_system_message = f"{system_message}\n\nContext about RAID club: {context}"
            
            self.chat_app = ChatApplication(
                api_key=os.getenv("OPENAI_API_KEY", ""),
                model=os.getenv("OPENAI_MODEL", ""),
                endpoint=os.getenv("OPENAI_ENDPOINT", ""),
                system_message=enhanced_system_message
            )
        
        console.print("[green]✓[/green] AI Chat Application ready")

    def read_files_content(self):
        """Read the content of the text files and return as a string"""
        files_content = ""
        # files_to_read = ["Stella_messages.txt", "RAID_info.txt"]
        files_to_read = ["RAID_info.txt"]
        
        for file_name in files_to_read:
            try:
                file_path = os.path.join("src", file_name)
                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8') as file:
                        files_content += f"\n\n--- Content from {file_name} ---\n{file.read()}"
                    console.print(f"[green]✓[/green] Filename {file_name} loaded successfully")
                else:
                    console.print(f"[yellow] ⚠ Warning: [/yellow] {file_name} not found")
            except Exception as e:
                console.print(f"[red]✗ [/red] Error reading {file_name}: {e}")
        
        return files_content

    def generate_response(self, user_email: str, user_name: str, step: int, incoming_message: dict = {}):
        """Generate initial welcome email response"""
        if step != 0:
            raise ValueError(f"This function only handles step 0 (initial email). Got step {step}")
        
        prompt = (
            f"Generate only the body of the initial welcome email for new member {user_name} <{user_email}>. "
            f"Do not include the subject line. The subject will be set separately. Use a friendly, "
            f"conversational tone. You may use **bold** for important points or emphasis where appropriate."
            f"Use bullet points (starting with -) for any lists or questions to ensure proper formatting."
            )

        if self.chat_app is None:
            console.print("[red]✗ [/red] ChatApplication not initialized")
            raise ValueError("ChatApplication is not initialized. Please ensure setup_chat_application() is called before generating a response.")
    
        response: str = self.chat_app.process_user_input(prompt)
        return response
    
    
    def read_emails_from_csv(self) -> list[dict]:
        """Read emails from CSV file and return list of dictionaries"""
        user_data = []
        try:
            # Get the directory where this script is located, then find the CSV
            script_dir = os.path.dirname(os.path.abspath(__file__))
            csv_path = os.path.join(script_dir, "email_address.csv")
            with open(csv_path, 'r', encoding='utf-8') as csv_file:
                reader = csv.DictReader(csv_file)
                for row in reader:
                    email = row.get('Email_Address', '').strip()
                    name = row.get('Name', '').strip()
                    if email and name:
                        user_data.append({"email": email, "name": name})
            console.print(f"[green]✓ [/green] Loaded {len(user_data)} users from CSV")
        except Exception as e:
            console.print(f"[red]✗ [/red] Error reading CSV: {e}")

        return user_data
    


    def start_conversation_flow(self, user_data: list[dict]):
        """Start the conversation flow for multiple users"""
        
        for user in user_data:
            email = user['email']
            name = user['name']
            try:
                console.status(f"[yellow]→ Processing {email}...[/yellow]", spinner="dots")
                
                # Generate initial AI response
                initial_response = self.generate_response(email, name, 0)
                
                # Display the raw markdown in cli using rich console
                self.workflow.display_rafael_message(initial_response, "Rafael - Initial Email")
                
                # Post-process email body and markdowns to format in HTML
                formatted_body = self.format_email_body(initial_response)
                
                # Send initial email
                thread_id = self.workflow.send_initial_email(
                    recipient=email,
                    subject="Welcome to RAID!",
                    body=formatted_body, name=name, raw_body=initial_response
                )
                
                # Track the thread
                self.active_threads[thread_id] = {
                    'email': email,
                    'step': 0,
                    'started_at': datetime.now()
                }
                
                console.print(f"[green]✓ [/green] Conversation started with {email}")
                console.print(f"[green]✓ [/green] Thread ID: {thread_id}...")
                
            except Exception as e:
                console.print(f"[red]✗ [/red] Error starting conversation with {email}: {e}")

    def display_workflow_status(self):
        """Display current workflow status"""
        if not self.active_threads:
            console.print("[yellow] Warning ⚠ [/yellow] No active conversations")
            return
        
        for thread_id, info in self.active_threads.items():
            console.print(f"{info['email']} - Thread {thread_id}... (Step {info['step']})")

    async def run_workflow(self):
        """Main workflow execution"""
        try:
            # Setup components
            self.setup_chat_application()
            
            # Setup enhanced integration with AI chat app and active threads
            self.workflow.setup_enhanced_integration(
                chat_app=self.chat_app,
                active_threads=self.active_threads
            )
            
            # Start Gmail listener
            listener_future = self.workflow.start_listening()
            
            # Define target users
            try:
                user_data = self.read_emails_from_csv()
            except Exception as e:
                test_email = os.getenv("RECIPIENT_TEST_EMAIL", "")
                test_name = os.getenv("RECIPIENT_TEST_NAME", "")
                user_data = [{"email": test_email, "name": test_name}]

            for user in user_data:
                console.print(user["email"])

                        
            
            # Start conversations
            console.print() # New Line for Spacing
            self.start_conversation_flow(user_data)
            
            # Display status
            console.print() # New Line for Spacing
            self.display_workflow_status()
            
            # Keep the workflow running
            console.print(Rule(style="white"))
            console.print("[dim]Press Ctrl+C to stop[/dim]")
            console.print("[green]Workflow active - Rafael monitoring for incoming emails ...[/green]")
            
            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                console.print("\n[yellow]Shutting down workflow...[/yellow]")
                self.workflow.stop_listening(listener_future)
                console.print("[red]Workflow stopped[/red]")
                
        except Exception as e:
            console.print(f"[red]Critical error in workflow execution: {e}[/red]")

async def main():
    """
    Main function that orchestrates the entire integrated workflow:
    1. Sets up AI chat application with context
    2. Initializes Gmail workflow with Pub/Sub listening
    3. Sends AI-generated initial emails
    4. Waits for responses and continues conversation loop (up to 3 exchanges)
    5. Processes sample data for database storage
    """
    workflow = IntegratedWorkflow()
    await workflow.run_workflow()
    
if __name__ == "__main__":
    asyncio.run(main())
