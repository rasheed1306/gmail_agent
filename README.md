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
3. **Data Extraction**: LLM parses conversations to structured fields
4. **Database Storage**: Application + workflow tracking tables
5. **Event Processing**: Gmail push → Pub/Sub topic → long-running listener

## Database Schema

```sql
CREATE TABLE IF NOT EXISTS club_applications (
  email VARCHAR(255) PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  conversation JSONB,
  major VARCHAR(255),
  motivation TEXT,
  desired_activities JSONB
);

CREATE TABLE IF NOT EXISTS workflows (
  id SERIAL PRIMARY KEY,
  thread_id VARCHAR(255) UNIQUE NOT NULL,
  step INTEGER NOT NULL DEFAULT 0,
  status VARCHAR(50) NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workflows_thread_id ON workflows(thread_id);
```

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

3. **Database Setup (Required for google-cloud-test.py)**

   - Create Supabase account at [supabase.com](https://supabase.com) or setup local PostgreSQL
   - Run the database schema above
   - Add to `.env`: `DATABASE_URL=your_connection_string` and `DATABASE_API_KEY=your_key`

4. Environment variables: copy `.env.example` → `.env`, then `source .env`

5. Google Cloud (Gmail Push + Pub/Sub)

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

6. Run

- Orchestrator (older workflow, single-reply, ~5 min await, no Pub/Sub): `uv run main.py`
- Integrated workflow (with CSV): `uv run src/mainV2.py`

## Files

- `main.py` — Older workflow (no Pub/Sub, awaits up to ~5 minutes, can only reply once per user; not designed for multi-exchange conversations)
- `mainV2.py` — Integrated workflow with CSV email loading, Database logging, Event driven pub/sub architecture
- `google_cloud.py` — Pub/Sub listener for Gmail push events
- `chat_manager.py` — LLM chat system
- `LLM_Extraction.py` — Information extraction
- `email_address.csv` — List of recipient emails for bulk conversations
- `.env.example` — Environment template

## Current Status

- Generates personalized emails
- Extracts and stores member info
- Handles multiple conversations
- Event-driven via Gmail + Pub/Sub (listener runs indefinitely)
- Response generation, database logging working in `main.py` with infinite event drive architecture on `google_cloud.py`
