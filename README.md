# Teams Meetings Agent

An AI-powered Microsoft Teams bot that monitors users' calendars for recording reminders, retrieves meeting transcripts and Copilot AI Insights, indexes transcripts in Azure AI Search, and supports per-transcript chat sessions.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Azure App Service (Always On)                      │
│                                                     │
│  ┌──────────────┐  ┌────────────┐  ┌────────────┐  │
│  │ Bot Endpoint  │  │  Webhook   │  │ Background │  │
│  │ /api/messages │  │/api/notify │  │ Scheduler  │  │
│  └──────┬───────┘  └─────┬──────┘  └─────┬──────┘  │
│         │                │               │          │
└─────────┼────────────────┼───────────────┼──────────┘
          │                │               │
          ▼                ▼               ▼
    ┌───────────┐   ┌───────────┐   ┌───────────────┐
    │ Azure Bot │   │ Microsoft │   │ Blob Storage  │
    │ Service   │   │   Graph   │   │ (user list +  │
    │ (Teams)   │   │ (Calendar,│   │  state)       │
    └───────────┘   │ Transcripts│  └───────────────┘
                    │ AI Insights│
                    └───────────┘
          │                               │
          ▼                               ▼
    ┌───────────┐                  ┌──────────────┐
    │ Azure     │                  │ Azure AI     │
    │ OpenAI    │                  │ Search       │
    │ (chat +   │                  │ (transcript  │
    │ embedding)│                  │  index)      │
    └───────────┘                  └──────────────┘
```

## Core Flows

### Flow 1 -- Recording Reminder

1. Background scheduler reads `monitored_users.json` from Blob Storage every N minutes.
2. For each user, queries `GET /users/{userId}/calendarView` for upcoming Teams meetings.
3. For meetings starting within the reminder window (default 15 min), sends a proactive Adaptive Card: "Meeting X starts soon -- remember to start recording."
4. Tracks sent reminders in-memory to avoid duplicates.

### Flow 2 -- Transcript Processing

1. App holds a tenant-level Graph subscription on `communications/onlineMeetings/getAllTranscripts`.
2. When a transcript becomes available, Graph sends a change notification to `/api/notifications`.
3. App fetches the VTT transcript via `GET /users/{userId}/onlineMeetings/{meetingId}/transcripts/{transcriptId}/content`.
4. App fetches Copilot AI Insights via `GET /copilot/users/{userId}/onlineMeetings/{meetingId}/aiInsights` for structured meeting notes, action items, and mention events.
5. Transcript text is chunked, embedded (Azure OpenAI `text-embedding-3-large`), and pushed to the AI Search index with metadata (subject, date, organizer, attendees).
6. Bot sends a proactive summary card to each monitored attendee with action items and a "Chat about this transcript" button.

### Flow 3 -- Transcript Chat

1. User clicks "Chat about transcript X" on the summary card or selects one from the transcript picker.
2. Bot opens a session keyed by `transcriptId` in the conversation state store.
3. Each user message is sent to Azure OpenAI with the full transcript as system context plus conversation history.
4. User can switch transcripts via the `transcripts` command.

### Flow 4 -- Cross-Meeting Search

1. User types `search: in what meeting did we discuss budget?` or similar.
2. Bot queries AI Search with hybrid search (keyword + vector).
3. Returns top results as Adaptive Cards with meeting subject, date, snippet, and a "Chat about this" action.

## Graph API Permissions (Application)

| Permission | Purpose |
|---|---|
| `Calendars.Read` | Discover upcoming meetings for monitored users |
| `OnlineMeetingTranscript.Read.All` | Subscribe to + fetch transcript content |
| `OnlineMeetingAiInsight.Read.All` | Fetch Copilot AI-generated summaries (requires Copilot license) |
| `User.Read.All` | Resolve user IDs from email/UPN |
| `OnlineMeetings.Read.All` | Resolve meeting details |
| `TeamsAppInstallation.ReadWriteSelfForUser.All` | Proactively install bot for monitored users |

An **Application Access Policy** must be created via Teams PowerShell to authorize the app for transcript and AI Insights access.

## Repository Layout

```
TEAMS-MEETINGS-AGENT/
├── deploy/
│   ├── deploy.config.toml           # All Azure + Graph + bot configuration
│   ├── deploy-infra.ps1             # Idempotent infrastructure provisioning
│   ├── deploy-app.ps1               # ZIP-deploy, blob seed, search index, manifest
│   └── assets/users/
│       └── monitored_users.json.example
├── src/
│   ├── app.py                       # aiohttp entry point
│   ├── bot.py                       # Teams ActivityHandler
│   ├── config.py                    # Settings from environment variables
│   ├── graph/
│   │   ├── auth.py                  # MSAL client credentials + Graph HTTP helpers
│   │   ├── calendar.py              # CalendarView queries
│   │   ├── transcripts.py           # Transcript metadata + VTT content
│   │   ├── insights.py              # Copilot AI Insights
│   │   ├── subscriptions.py         # Graph change notification subscriptions
│   │   └── users.py                 # User resolution
│   ├── services/
│   │   ├── reminder.py              # Calendar scan + proactive reminders
│   │   ├── transcript_processor.py  # Fetch + index + notify orchestration
│   │   ├── search.py                # AI Search indexing + hybrid query
│   │   └── chat.py                  # Per-transcript chat via Azure OpenAI
│   ├── webhooks/
│   │   ├── notification_handler.py  # Graph change notification endpoint
│   │   └── validation.py            # Subscription validation handshake
│   ├── cards/
│   │   ├── reminder_card.py         # Recording reminder Adaptive Card
│   │   ├── summary_card.py          # Meeting summary Adaptive Card
│   │   ├── transcript_picker_card.py
│   │   └── search_results_card.py
│   ├── background/
│   │   └── scheduler.py             # APScheduler for reminders + subscription renewal
│   └── state/
│       └── conversation_state.py    # In-memory transcript session + chat history
├── manifest/
│   ├── manifest.json                # Teams app manifest (placeholders replaced at deploy)
│   ├── color.png
│   └── outline.png
├── requirements.txt
├── README.md
└── .gitignore
```

## Configuration

All configuration lives in [`deploy/deploy.config.toml`](deploy/deploy.config.toml).

| Section | Key fields |
|---|---|
| `[azure]` | `subscription_id`, `location`, `resource_group_name` |
| `[naming]` | `prefix`, `web_app_name`, `storage_account_name`, `openai_account_name`, `search_service_name`, `bot_name` |
| `[storage]` | `users_container`, `state_container` |
| `[entra]` | `app_display_name`, `app_id`, `app_secret` |
| `[graph]` | `reminder_window_minutes`, `scheduler_interval_minutes`, `subscription_renewal_minutes` |
| `[openai]` | `chat_deployment`, `embedding_deployment`, `api_version` |
| `[search]` | `index_name`, `sku`, `use_vector`, `embedding_dimensions` |
| `[bot]` | `bot_sku` |

If naming fields are left empty, they are derived from `naming.prefix`.

## Deployment

### Prerequisites

- Azure CLI (`az`) authenticated
- Python 3.11+
- PowerShell 7+
- Teams admin access (for Application Access Policy)

### Step 1: Provision Infrastructure

```powershell
.\deploy\deploy-infra.ps1
```

Creates (idempotently): Resource Group, Storage Account, App Service Plan + Web App (Always On), Azure OpenAI + deployments, AI Search, Entra App Registration + secret, Azure Bot Service + Teams channel, RBAC assignments, and Web App settings.

**After running**, follow the printed instructions to create the Application Access Policy in Teams PowerShell:

```powershell
Connect-MicrosoftTeams
New-CsApplicationAccessPolicy -Identity "MeetingsAgent-Policy" `
  -AppIds "<your-app-id>" -Description "Meetings agent access"
Grant-CsApplicationAccessPolicy -PolicyName "MeetingsAgent-Policy" -Global
```

### Step 2: Grant Admin Consent

In the Azure Portal, navigate to your app registration and grant admin consent for the required Graph permissions.

### Step 3: Seed and Deploy

1. Copy `deploy/assets/users/monitored_users.json.example` to `deploy/assets/users/monitored_users.json` and fill in the UPNs of users to monitor.

2. Deploy:

```powershell
.\deploy\deploy-app.ps1
```

This ZIP-deploys the web app, seeds the monitored users blob, creates/updates the AI Search index, and builds the Teams manifest ZIP.

### Step 4: Install the Teams App

Upload `deploy/teams-manifest.zip` via the Teams Admin Center or sideload for testing.

## Assumptions

- Monitored users have **Microsoft 365 Copilot licenses** (AI Insights API is the primary summarization source).
- **Admin consent** is granted for the listed Graph application permissions.
- Uses **Bot Framework SDK for Python** (stable). The new Teams SDK supports Python in developer preview; can migrate later.
- **App Service Plan B1+** with Always On for background scheduler reliability.
- **Single-tenant** Entra app registration (bot identity and Graph client share the same app).
- **Application Access Policy** is granted tenant-wide for simplicity.

## Key Microsoft Docs

- [Meeting AI Insights API](https://learn.microsoft.com/en-us/microsoftteams/platform/graph-api/meeting-transcripts/meeting-insights)
- [Transcript change notifications](https://learn.microsoft.com/en-us/graph/teams-changenotifications-callrecording-and-calltranscript)
- [Get callTranscript + content](https://learn.microsoft.com/en-us/graph/api/calltranscript-get)
- [Send proactive messages](https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/conversations/send-proactive-messages)
- [Application access policy](https://learn.microsoft.com/en-us/graph/cloud-communication-online-meeting-application-access-policy)
- [Bot overview](https://learn.microsoft.com/en-us/microsoftteams/platform/bots/what-are-bots)
- [Microsoft sample: bot-meeting-ai-insights/python](https://github.com/OfficeDev/Microsoft-Teams-Samples/tree/main/samples/bot-meeting-ai-insights/python)
