# Sentiment Analysis

PromptDev includes real-time sentiment analysis for chat messages using a 5-dimensional Relational Affect Model.

## Architecture

```
User Message → Venice.ai LLM → AffectVector[5] → Database → Context Injection
```

The system analyzes each user message and:
1. Extracts 5-dimensional affect vectors
2. Stores results in `message_sentiment` table
3. Computes session aggregates
4. Optionally injects sentiment context into LLM prompts

## Affect Dimensions

| Dimension | Range | Description |
|-----------|-------|-------------|
| **Valence** | -1 to 1 | Emotional positivity (negative ↔ positive) |
| **Arousal** | 0 to 1 | Energy level (calm ↔ excited/agitated) |
| **Dominance** | 0 to 1 | Assertiveness (submissive ↔ dominant) |
| **Trust** | 0 to 1 | Openness/vulnerability (guarded ↔ trusting) |
| **Engagement** | 0 to 1 | Investment in conversation (disengaged ↔ engaged) |

### Overall Score

Weighted composite: `valence×0.2 + arousal×0.1 + dominance×0.1 + trust×0.3 + engagement×0.3`

Trust and engagement are weighted higher for relational context.

## Usage

### Enable for a Session

Sentiment analysis is per-session. Enable via admin dashboard or API:

```bash
# Toggle sentiment for a session
curl -X POST "https://your-domain/admin/sessions/{session_id}/sentiment/toggle?enabled=true" \
  -b cookies.txt
```

Or when creating a new session:

```bash
curl -X POST "https://your-domain/chat/sessions?user_id=user123&sentiment_enabled=true" \
  -b cookies.txt
```

### View Sentiment Data

```bash
# Get sentiment history for a session
curl "https://your-domain/admin/sessions/{session_id}/sentiment" -b cookies.txt

# Get aggregated sentiment
curl "https://your-domain/admin/sessions/{session_id}/sentiment/aggregate" -b cookies.txt

# Get sentiment for a specific message
curl "https://your-domain/admin/messages/{message_id}/sentiment" -b cookies.txt
```

## Database Schema

### message_sentiment

| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| message_id | int | FK to conversation_history |
| session_id | int | FK to chat_sessions |
| valence | float | -1 to 1 |
| arousal | float | 0 to 1 |
| dominance | float | 0 to 1 |
| trust | float | 0 to 1 |
| engagement | float | 0 to 1 |
| overall_sentiment | float | Weighted composite |
| confidence | float | Model confidence (0-1) |
| injection_context | text | Context string injected into prompt |
| created_at | timestamp | When analyzed |

### sentiment_aggregates

| Column | Type | Description |
|--------|------|-------------|
| session_id | int | FK to chat_sessions |
| window_type | text | "session", "hourly", etc. |
| avg_valence | float | Average valence |
| avg_arousal | float | Average arousal |
| avg_dominance | float | Average dominance |
| avg_trust | float | Average trust |
| avg_engagement | float | Average engagement |
| valence_trend | float | Linear regression slope |
| engagement_trend | float | Linear regression slope |
| message_count | int | Messages in window |

## Context Injection

When sentiment is enabled, recent affect data is summarized and injected into the LLM prompt:

```
[User sentiment: positive and upbeat, highly engaged, open and trusting]
```

This helps the AI companion respond appropriately to the user's emotional state.

### Thresholds

| Dimension | Low (<0.3) | Neutral | High (>0.7) |
|-----------|-----------|---------|-------------|
| Valence | "frustrated or upset" | - | "positive and upbeat" |
| Arousal | "calm/subdued" | - | "energetic/excited" |
| Trust | "guarded" | - | "open and trusting" |
| Engagement | "disengaged" | - | "highly engaged" |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/sessions/{id}/sentiment/toggle` | POST | Enable/disable sentiment |
| `/admin/sessions/{id}/sentiment` | GET | Get sentiment history |
| `/admin/sessions/{id}/sentiment/aggregate` | GET | Get aggregated sentiment |
| `/admin/messages/{id}/sentiment` | GET | Get single message sentiment |

## Implementation Details

### LLM-Based Analysis

Unlike traditional ML sentiment models, PromptDev uses an LLM (Venice.ai) to extract affect dimensions. The prompt asks the model to rate each dimension with JSON output:

```json
{
  "valence": 0.6,
  "arousal": 0.4,
  "dominance": 0.5,
  "trust": 0.7,
  "engagement": 0.8,
  "confidence": 0.85
}
```

### Async Processing

Sentiment analysis runs asynchronously during chat to avoid blocking responses. If analysis fails, the chat continues normally with a warning logged.

### Confidence Scores

The model returns a confidence score (0-1) indicating reliability of the analysis. Low confidence results are still stored but can be filtered in queries.

## Configuration

Sentiment analysis uses the same Venice.ai configuration as chat:

```toml
[venice]
url = "https://api.venice.ai/api/v1"
model = "mistral-31-24b"
```

Environment variable required:
```bash
VENICE_API_KEY=your_key
```

## Admin Dashboard

The admin dashboard shows:
- Per-message sentiment indicators
- Session aggregate scores (Avg Valence, Avg Trust, Engagement)
- Sentiment toggle per session
- Global sentiment toggle in settings

## Migrations

Required migration: `013_sentiment.sql`

```sql
-- Adds sentiment_enabled to chat_sessions
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS sentiment_enabled BOOLEAN DEFAULT true;

-- Creates message_sentiment and sentiment_aggregates tables
```

Run with:
```bash
make db-migrate db=remote
```
