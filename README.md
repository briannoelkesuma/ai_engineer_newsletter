# 🚀 AI Engineer YouTube Newsletter & Intelligence Pipeline

An automated, serverless intelligence pipeline that extracts transcripts from new uploads on the **[AI Engineer YouTube Channel](https://www.youtube.com/@ai_engineer)**, generates structured technical deep dives using LLMs (Llama 3.3 70B & Gemma 4 on OpenRouter), broadcasts alerts to dedicated **Telegram Sub-Channels (Forum Topics)**, synthesizes executive catch-up digests for unopened backlogs, and compiles a fast static knowledge hub hosted on **GitHub Pages**.

---

## 🌟 Key Features

1. **Instant WebSub Ingestion**: YouTube proactively notifies our Cloudflare Worker the second a video goes live (zero polling, zero API quota drain).
2. **Robust Transcript Extraction**: Downloads full subtitles via `yt-dlp` with proxy rotation, timestamps, and multi-tier scraping fallbacks.
3. **Deep Technical Synthesis**: Utilizes Map-Reduce chunking and cascading LLM fallbacks to generate comprehensive, timestamped takeaways.
4. **Telegram Sub-Channels (Forum Topics)**:
   - 📹 **`#Video Updates`**: Detailed individual breakdowns for every newly published talk.
   - ⚡ **`#Catch-up Digests`**: Synthesized executive briefs that summarize unopened backlogs so you never feel overwhelmed.
5. **Interactive Telegram Bot Commands**:
   - `/digest` — Instantly generates an AI synthesized briefing of all unopened videos.
   - `/unread` — Shows how many video summaries are waiting in your queue.
   - `/markread` — Clears your backlog and marks all existing summaries as read.
   - `/help` — Lists available commands.
6. **Searchable Knowledge Archive**: Automatically rebuilds and deploys a clean static HTML digest to **GitHub Pages**.
7. **100% Free & Serverless**: Runs completely on Cloudflare Workers (free tier), GitHub Actions (free tier), Supabase (free tier), and GitHub Pages.
8. **Serverless Interactive Webhooks**: 24/7 interactive response to Telegram commands via Cloudflare to GitHub Actions routing.

---

## 🏛 Architecture Diagram

```mermaid
flowchart TD
    subgraph 1. YouTube & Edge Ingestion
        A[New Video Published] -->|WebSub Push| B[Cloudflare Worker]
        B -->|1. Deduplicate & Insert status='pending'| C[(Supabase DB: 'videos')]
        B -->|2. Trigger Workflow Dispatch| D[GitHub Actions Runner]
    end

    subgraph 2. Ingestion & Analysis Engine
        D -->|3. Fetch Subtitles with Proxy Rotation| E[yt-dlp / Fallback Scrapers]
        E -->|4. Map-Reduce Ingestion| F[LLM Cascade / OpenRouter]
        F -->|5. Save HTML & Mark 'processed'| C
    end

    subgraph 3. Distribution & Presentation
        F -->|6. Send Video Breakdown| G[Telegram: General Chat]
        D -->|7. Rebuild public/index.html & Commit| H[GitHub Pages Archive]
        USER[User on Telegram] -->|/digest Command| WEBHOOK[Cloudflare Webhook]
        WEBHOOK -->|Trigger Action| I[GitHub Action: telegram_commands.yml]
        I -->|8. Send Executive Catch-Up Digest| J[Telegram Topic: #Catch-up Digests]
    end
```

---

## 📂 Telegram Topic & Sub-Channel Routing

The pipeline sends messages to specific sub-channels (topics) in your Telegram Supergroup:

| Topic / Sub-Channel | Thread ID | Description |
|---|---|---|
| 📹 **General Chat** | *(Empty / None)* | Receives individual video breakdowns with key ideas, architecture takeaways, and links. |
| ⚡ **Catch-up Digests** | `TELEGRAM_DIGEST_THREAD_ID` | Receives high-level executive summaries synthesizing across multiple unopened videos. |

---

## 🔄 Self-Healing & Pipeline Resiliency

* **Automatic Stuck Job Recovery**: Automatically resets any orphan `processing` status videos back to `pending` on startup if a runner is interrupted.
* **Cascading LLM Fallbacks**: OpenRouter `Llama 3.3 70B` ➔ `Google Gemma 4 26B` with exponential retry backoff.
* **Capped Retry Budgets**: Prevents infinite loops on corrupt videos by pausing after 3 attempts and reviving them during daily cron checks.
* **Outbound IP Proxy Rotation**: Rotates outbound requests through proxies in `YOUTUBE_PROXY` to prevent YouTube bot detection.

---

## 🛠 Verification & Testing

### 1. Verify Telegram Sub-Channels
Test message delivery to both topics:
```bash
python telegram_bot.py test
```

### 2. Verify Catch-Up Digest Generation
Generate a fresh executive brief of unopened videos:
```bash
python catchup_digest.py
```

### 3. Verify Local Video Pipeline
Test subtitle extraction and LLM summarization on a single video:
```bash
python main.py <YOUTUBE_VIDEO_ID>
```

### 4. Verify GitHub Actions Pipeline
1. Go to your repository on GitHub.
2. Navigate to **Actions** ➔ **Process YouTube Videos**.
3. Click **Run workflow** ➔ Select `main` branch ➔ **Run workflow**.

### 5. Verify WebSub Subscription
Check Google's official hub registration status:
👉 **[Google PubSubHubbub Diagnostics Portal](https://pubsubhubbub.appspot.com/subscription-details?hub.callback=https://youtube-websub-worker.2612brian.workers.dev&hub.topic=https://www.youtube.com/xml/feeds/videos.xml?channel_id=UCLKPca3kwwd-B59HNr-_lvA&hub.secret=54117b8f2a3df29c2d79d7f5a03496f8c7e2d9a3)**

---

## ⚙️ Environment Variables & Secrets

Add these secrets to your local `.env` and GitHub repository (`Settings ➔ Secrets and variables ➔ Actions`):

```ini
SUPABASE_URL=https://<your-project>.supabase.co
SUPABASE_KEY=<your-service-role-key>

OPENROUTER_API_KEY=sk-or-v1-...
DEFAULT_MODEL=google/gemma-4-26b-a4b-it:free

TELEGRAM_BOT_TOKEN=8973031968:...
TELEGRAM_CHAT_ID=-1004311421904
TELEGRAM_SUMMARY_THREAD_ID=
TELEGRAM_DIGEST_THREAD_ID=2

GITHUB_TOKEN=ghp_...
WEBHOOK_SECRET=54117b8f...
YOUTUBE_PROXY=http://user:pass@proxy1:port,http://user:pass@proxy2:port
```

---

## 📁 Repository Map

```
ai_engineer_newsletter/
├── .github/workflows/
│   ├── process_videos.yml     # Video ingestion automated workflow
│   └── telegram_commands.yml  # Interactive serverless telegram webhook response
├── youtube-websub-worker/     # Cloudflare Worker code
│   ├── src/index.js           # WebSub webhook handler & GitHub dispatcher
│   └── wrangler.toml          # Worker configuration & Cron triggers
├── public/
│   └── index.html             # Compiled static archive site for GitHub Pages
├── main.py                    # Main pipeline orchestrator
├── catchup_digest.py          # Multi-video executive briefing generator
├── telegram_bot.py            # Telegram Bot client & topic routing
├── llm_analyzer.py            # OpenRouter / Gemini inference engine
├── transcript_fetcher.py      # Subtitle extraction with proxy rotation
├── ingestor.py                # Fallback web scraping utilities
├── generate_static_site.py    # Static HTML site builder
├── db.py                      # Supabase client abstraction
├── user_state.json            # Local unread video tracker
├── AGENT.md                   # Technical onboarding guide for AI agents
└── README.md                  # System overview and operational manual
```

---

## 📄 License
MIT License. Built for the AI Engineer community.