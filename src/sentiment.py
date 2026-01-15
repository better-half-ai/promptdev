"""
Sentiment analysis for chat messages.

Implements 5-dimensional Relational Affect Model:
- Valence: positive/negative (-1 to 1)
- Arousal: calm/excited (0 to 1)  
- Dominance: submissive/dominant (0 to 1)
- Trust: distrust/trust (0 to 1)
- Engagement: disengaged/engaged (0 to 1)
"""

import logging
import os
from typing import Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from pydantic import BaseModel, ConfigDict
import json
import httpx

from db.db import get_conn, put_conn
from src.config import get_config

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class AffectVector:
    """5-dimensional affect representation."""
    valence: float      # -1 to 1
    arousal: float      # 0 to 1
    dominance: float    # 0 to 1
    trust: float        # 0 to 1
    engagement: float   # 0 to 1
    
    @property
    def overall(self) -> float:
        """Weighted composite score."""
        # Weight trust and engagement higher for relational context
        return (
            self.valence * 0.2 +
            self.arousal * 0.1 +
            self.dominance * 0.1 +
            self.trust * 0.3 +
            self.engagement * 0.3
        )
    
    def to_dict(self) -> dict:
        return {
            "valence": self.valence,
            "arousal": self.arousal,
            "dominance": self.dominance,
            "trust": self.trust,
            "engagement": self.engagement,
            "overall": self.overall
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> "AffectVector":
        return cls(
            valence=d.get("valence", 0),
            arousal=d.get("arousal", 0.5),
            dominance=d.get("dominance", 0.5),
            trust=d.get("trust", 0.5),
            engagement=d.get("engagement", 0.5)
        )
    
    @classmethod
    def neutral(cls) -> "AffectVector":
        """Return neutral affect vector."""
        return cls(valence=0, arousal=0.5, dominance=0.5, trust=0.5, engagement=0.5)


class MessageSentiment(BaseModel):
    """Sentiment analysis result for a message."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    message_id: int
    session_id: Optional[int] = None
    valence: float
    arousal: float
    dominance: float
    trust: float
    engagement: float
    overall_sentiment: float
    confidence: float
    created_at: datetime


class SentimentAggregate(BaseModel):
    """Aggregated sentiment for a time window."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    session_id: int
    window_start: datetime
    window_type: str
    avg_valence: float
    avg_arousal: float
    avg_dominance: float
    avg_trust: float
    avg_engagement: float
    valence_trend: Optional[float] = None
    engagement_trend: Optional[float] = None
    message_count: int


# ═══════════════════════════════════════════════════════════════════════════
# ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

async def analyze_message(text: str, context: Optional[list[dict]] = None) -> tuple[AffectVector, float]:
    """
    Analyze sentiment of a message.
    Returns (affect_vector, confidence).
    
    Uses LLM to extract relational affect dimensions.
    """
    config = get_config()
    
    # Build analysis prompt
    context_text = ""
    if context:
        recent = context[-5:]  # Last 5 messages for context
        context_text = "\n".join([f"{m['role']}: {m['content'][:200]}" for m in recent])
        context_text = f"\nRecent conversation context:\n{context_text}\n"
    
    prompt = f"""Analyze the emotional and relational affect of this message.
{context_text}
Message to analyze: "{text}"

Rate each dimension from the speaker's perspective:
- valence: emotional positivity (-1 very negative to 1 very positive)
- arousal: energy level (0 very calm to 1 very excited/agitated)
- dominance: assertiveness (0 very submissive to 1 very dominant)
- trust: openness/vulnerability (0 very guarded to 1 very trusting)
- engagement: investment in conversation (0 very disengaged to 1 very engaged)

Respond ONLY with JSON:
{{"valence": 0.0, "arousal": 0.5, "dominance": 0.5, "trust": 0.5, "engagement": 0.5, "confidence": 0.8}}"""

    try:
        api_key = os.environ.get("VENICE_API_KEY", "")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{config.venice.url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": config.venice.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 150
                }
            )
            response.raise_for_status()
            
            result = response.json()
            content = result["choices"][0]["message"]["content"].strip()
            
            # Parse JSON response
            # Handle potential markdown code blocks
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            
            data = json.loads(content)
            confidence = data.pop("confidence", 0.8)
            
            return AffectVector.from_dict(data), confidence
            
    except Exception as e:
        logger.warning(f"Sentiment analysis failed: {e}, using neutral")
        return AffectVector.neutral(), 0.0


def analyze_message_sync(text: str, context: Optional[list[dict]] = None) -> tuple[AffectVector, float]:
    """Synchronous wrapper for analyze_message."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(analyze_message(text, context))


# ═══════════════════════════════════════════════════════════════════════════
# STORAGE
# ═══════════════════════════════════════════════════════════════════════════

def store_sentiment(
    message_id: int,
    affect: AffectVector,
    confidence: float,
    session_id: Optional[int] = None,
    raw_output: Optional[dict] = None,
    model_version: Optional[str] = None,
    injection_context: Optional[str] = None
) -> int:
    """Store sentiment analysis result."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO message_sentiment 
                (message_id, session_id, valence, arousal, dominance, trust, engagement,
                 overall_sentiment, confidence, raw_output, model_version, injection_context)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (message_id) DO UPDATE SET
                    valence = EXCLUDED.valence,
                    arousal = EXCLUDED.arousal,
                    dominance = EXCLUDED.dominance,
                    trust = EXCLUDED.trust,
                    engagement = EXCLUDED.engagement,
                    overall_sentiment = EXCLUDED.overall_sentiment,
                    confidence = EXCLUDED.confidence,
                    injection_context = EXCLUDED.injection_context
                RETURNING id
                """,
                (message_id, session_id, affect.valence, affect.arousal, affect.dominance,
                 affect.trust, affect.engagement, affect.overall, confidence,
                 json.dumps(raw_output) if raw_output else None, model_version, injection_context)
            )
            sentiment_id = cur.fetchone()[0]
            conn.commit()
            return sentiment_id
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to store sentiment: {e}")
        raise
    finally:
        put_conn(conn)


def get_message_sentiment(message_id: int) -> Optional[MessageSentiment]:
    """Get sentiment for a specific message."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, message_id, session_id, valence, arousal, dominance, trust, 
                       engagement, overall_sentiment, confidence, created_at
                FROM message_sentiment WHERE message_id = %s
                """,
                (message_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return MessageSentiment(
                id=row[0], message_id=row[1], session_id=row[2],
                valence=row[3], arousal=row[4], dominance=row[5],
                trust=row[6], engagement=row[7], overall_sentiment=row[8],
                confidence=row[9], created_at=row[10]
            )
    finally:
        put_conn(conn)


def get_session_sentiment(
    session_id: int,
    limit: int = 50
) -> list[dict]:
    """Get sentiment history for a session."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, message_id, session_id, valence, arousal, dominance, trust,
                       engagement, overall_sentiment, confidence, created_at, injection_context
                FROM message_sentiment 
                WHERE session_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (session_id, limit)
            )
            return [
                {
                    "id": row[0],
                    "message_id": row[1],
                    "session_id": row[2],
                    "valence": row[3],
                    "arousal": row[4],
                    "dominance": row[5],
                    "trust": row[6],
                    "engagement": row[7],
                    "overall_sentiment": row[8],
                    "confidence": row[9],
                    "created_at": row[10].isoformat() if row[10] else None,
                    "injection_context": row[11]
                }
                for row in cur.fetchall()
            ]
    finally:
        put_conn(conn)


def get_recent_affect(session_id: int, count: int = 5) -> list[AffectVector]:
    """Get recent affect vectors for context injection."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT valence, arousal, dominance, trust, engagement
                FROM message_sentiment
                WHERE session_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (session_id, count)
            )
            return [
                AffectVector(
                    valence=row[0], arousal=row[1], dominance=row[2],
                    trust=row[3], engagement=row[4]
                )
                for row in cur.fetchall()
            ]
    finally:
        put_conn(conn)


# ═══════════════════════════════════════════════════════════════════════════
# AGGREGATION
# ═══════════════════════════════════════════════════════════════════════════

def compute_session_aggregate(session_id: int, window_type: str = "session") -> Optional[SentimentAggregate]:
    """Compute aggregate sentiment for a session."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 
                    AVG(valence), AVG(arousal), AVG(dominance), AVG(trust), AVG(engagement),
                    COUNT(*)
                FROM message_sentiment
                WHERE session_id = %s
                """,
                (session_id,)
            )
            row = cur.fetchone()
            if not row or row[5] == 0:
                return None
            
            # Compute trends (simple linear regression slope)
            cur.execute(
                """
                SELECT 
                    REGR_SLOPE(valence, EXTRACT(EPOCH FROM created_at)),
                    REGR_SLOPE(engagement, EXTRACT(EPOCH FROM created_at))
                FROM message_sentiment
                WHERE session_id = %s
                """,
                (session_id,)
            )
            trend_row = cur.fetchone()
            
            now = datetime.utcnow()
            
            # Store aggregate
            cur.execute(
                """
                INSERT INTO sentiment_aggregates
                (session_id, window_start, window_type, avg_valence, avg_arousal, avg_dominance,
                 avg_trust, avg_engagement, valence_trend, engagement_trend, message_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (session_id, window_type, window_start) DO UPDATE SET
                    avg_valence = EXCLUDED.avg_valence,
                    avg_arousal = EXCLUDED.avg_arousal,
                    avg_dominance = EXCLUDED.avg_dominance,
                    avg_trust = EXCLUDED.avg_trust,
                    avg_engagement = EXCLUDED.avg_engagement,
                    valence_trend = EXCLUDED.valence_trend,
                    engagement_trend = EXCLUDED.engagement_trend,
                    message_count = EXCLUDED.message_count
                RETURNING id
                """,
                (session_id, now, window_type, row[0], row[1], row[2], row[3], row[4],
                 trend_row[0] if trend_row else None, trend_row[1] if trend_row else None, row[5])
            )
            agg_id = cur.fetchone()[0]
            conn.commit()
            
            return SentimentAggregate(
                id=agg_id, session_id=session_id, window_start=now, window_type=window_type,
                avg_valence=row[0], avg_arousal=row[1], avg_dominance=row[2],
                avg_trust=row[3], avg_engagement=row[4],
                valence_trend=trend_row[0] if trend_row else None,
                engagement_trend=trend_row[1] if trend_row else None,
                message_count=row[5]
            )
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to compute aggregate: {e}")
        return None
    finally:
        put_conn(conn)


# ═══════════════════════════════════════════════════════════════════════════
# CONTEXT GENERATION (for prompt injection)
# ═══════════════════════════════════════════════════════════════════════════

def generate_sentiment_context(session_id: int) -> str:
    """
    Generate sentiment context string for prompt injection.
    Returns a natural language summary of recent emotional state.
    """
    affects = get_recent_affect(session_id, count=5)
    if not affects:
        return ""
    
    # Average recent affects
    avg = AffectVector(
        valence=sum(a.valence for a in affects) / len(affects),
        arousal=sum(a.arousal for a in affects) / len(affects),
        dominance=sum(a.dominance for a in affects) / len(affects),
        trust=sum(a.trust for a in affects) / len(affects),
        engagement=sum(a.engagement for a in affects) / len(affects)
    )
    
    # Generate natural language description
    parts = []
    
    # Valence
    if avg.valence > 0.3:
        parts.append("positive and upbeat")
    elif avg.valence < -0.3:
        parts.append("frustrated or upset")
    
    # Arousal
    if avg.arousal > 0.7:
        parts.append("energetic/excited")
    elif avg.arousal < 0.3:
        parts.append("calm/subdued")
    
    # Trust
    if avg.trust > 0.7:
        parts.append("open and trusting")
    elif avg.trust < 0.3:
        parts.append("guarded")
    
    # Engagement
    if avg.engagement > 0.7:
        parts.append("highly engaged")
    elif avg.engagement < 0.3:
        parts.append("disengaged")
    
    if not parts:
        return "[User sentiment: neutral]"
    
    return f"[User sentiment: {', '.join(parts)}]"
