# RAID Club Email Agent

An autonomous AI system that manages email correspondence with new RAID (Responsive AI Development) club members at the University of Melbourne.

## What It Does

- **Initiates conversations** with new members through personalized welcome emails
- **Handles multiple users** by reading recipient emails from `email_address.csv`
- **Extracts key information** using LLM analysis of email exchanges
- **Stores structured data** in Postgres/Supabase for member management
- **Processes Gmail events** via Google Pub/Sub push notifications
- **Operates autonomously** without manual intervention

## Key Features

- **Smart Email Generation**: Personalized welcome messages
- **Information Extraction**: Major, motivation, activity preferences
- **Database Integration**: Raw conversations + extracted insights
- **Workflow Tracking**: Conversation thread state and progress

## How It Works

1. **Email Initiation**: AI agent (Rafael) sends personalized welcome emails
2. **Conversation Management**: Handles back-and-forth email threads
3. **Database Storage**: Stores messages, users and workflow management data
4. **Event Processing**: Gmail push → Pub/Sub topic → long-running listener
5. **Markdown → HTML**: Render markdown to HTML before sending messages so recipients see styled content across mail clients

## Database Schema

```sql

-- Clean up in dependency order in case you're rerunning the migration
DROP TABLE IF EXISTS emails CASCADE;
DROP TABLE IF EXISTS email_workflow CASCADE;
DROP TABLE IF EXISTS email_users CASCADE;
DROP TYPE IF EXISTS sender_type;

-- 1) Enum for sender
CREATE TYPE sender_type AS ENUM ('user', 'agent');

-- 2) Users table (email directory for Gmail agent)
CREATE TABLE email_users (
    users_email_id SERIAL PRIMARY KEY,
    email TEXT NOT NULL,
    name TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_email_users_email UNIQUE (email)
);

COMMENT ON TABLE email_users IS 'Stores user information for the Gmail agent.';

-- 3) Emails (messages) table
CREATE TABLE emails (
    thread_id TEXT NOT NULL,
    email_id TEXT NOT NULL,
    user_email TEXT NOT NULL,
    sender sender_type NOT NULL,
    body TEXT NOT NULL,
    subject TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (email_id),
    CONSTRAINT fk_emails_user_email
        FOREIGN KEY (user_email)
        REFERENCES email_users(email)
        ON DELETE CASCADE
);

COMMENT ON TABLE emails IS 'Stores individual email messages for the Gmail agent.';

-- 4) Workflow log table
CREATE TABLE IF NOT EXISTS email_workflow (
  id SERIAL PRIMARY KEY,
  thread_id VARCHAR(255) UNIQUE NOT NULL,
  step INTEGER NOT NULL DEFAULT 0,
  status VARCHAR(50) NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- 5) Indexes
CREATE INDEX IF NOT EXISTS idx_emails_thread_id ON emails(thread_id);
CREATE INDEX IF NOT EXISTS idx_emails_user_email ON emails(user_email);
CREATE INDEX IF NOT EXISTS idx_emails_timestamp ON emails(timestamp);
CREATE INDEX IF NOT EXISTS idx_email_workflow_thread_id ON email_workflow(thread_id);

COMMIT;


## Setup

1. Install dependencies: `uv install`

2. **Configure Email Recipients**

   - Create `src/email_address.csv` with the following format:
     ```csv
     Name,Email_Address
     John Doe,john.doe@example.com
     Jane Smith,jane.smith@example.com
     ```
   - This file controls which users receive initial welcome emails and enables handling multiple conversations simultaneously

3. **Database Setup & Environment Variables**

   - Create a `.env` file by copying `.env.example` and populate it with your credentials. This file centralizes configuration for the application's different services.
   - **Core Services**:
     - `OPENAI_API_KEY`, `OPENAI_ENDPOINT`, `OPENAI_MODEL`: For connecting to the language model.
     - `DATABASE_URL`, `DATABASE_API_KEY`: For connecting to your Supabase/PostgreSQL database.
   - **Google Cloud & Gmail**:
     - `GOOGLE_CLOUD_PROJECT`, `PROJECT_ID`, `TOPIC_NAME`, `SUBSCRIPTION_NAME`: For Pub/Sub integration.
     - `GMAIL_ADDRESS`: The Gmail account the agent will use.
   - **Testing**:
     - `RECIPIENT_TEST_EMAIL`, `RECIPIENT_TEST_NAME`: For sending test emails.

4. Google Cloud (Gmail Push + Pub/Sub)

   - Install gcloud SDK: see [Install the Google Cloud CLI](https://cloud.google.com/sdk/docs/install)
   - Authenticate and set project:
     ```bash
     gcloud init
     ```
   - Enable services and set Pub/Sub permissions:

     ```bash
     gcloud services enable gmail.googleapis.com
     gcloud services enable pubsub.googleapis.com
     ```

     # Allow Gmail push service account to publish to your topic:

     ```bash
     gcloud pubsub topics add-iam-policy-binding ${TOPIC_NAME} \
     --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
     --role="roles/pubsub.publisher" \
     --project=${PROJECT_ID}
     ```

5. Run

- Orchestrator (older workflow, single-reply, ~5 min await, no Pub/Sub): `uv run main.py`
- Integrated workflow (with CSV): `uv run src/mainV2.py`

## Files

- `main.py` — Older workflow (no Pub/Sub, awaits up to ~5 minutes, can only reply once per user; not designed for multi-exchange conversations)
- `mainV2.py` — Integrated workflow with CSV email loading, Database logging, Event driven pub/sub architecture
- `google_cloud.py` — Pub/Sub listener for Gmail push events
- `chat_manager.py` — LLM chat system
- `LLM_Extraction.py` — Information extraction
- `email_address.csv` — List of recipient emails for bulk conversations
- `database.py` — Handles databse operations, including logging for users and messages
- `.env.example` — Environment template

## Current Status

- Generates personalized emails
- Extracts and stores member info in Postgres/Supabase
- Handles multiple conversations autonomously
- Event-driven via Gmail + Pub/Sub (listener runs indefinitely)
- **main.py (Older Version)**: Generates personalized emails, handles single-reply conversations with ~5-minute polling delays, basic database logging for extracted member info (no Pub/Sub or multi-user support)
- **mainV2.py (Newer Version)**: Supports multiple users via CSV, event-driven processing with Gmail Pub/Sub for real-time responses, comprehensive database logging for users and messages, workflow tracking for conversation states
