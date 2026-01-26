"""
Session Store - Conversation memory for multi-turn interactions.

Provides in-memory session storage for tracking conversation history
and patterns across multiple turns.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
import threading


@dataclass
class Session:
    """A conversation session with history tracking."""
    
    id: str
    created: datetime = field(default_factory=datetime.now)
    history: List[Dict[str, Any]] = field(default_factory=list)  # [{role, content, ts}]
    mistakes_made: List[str] = field(default_factory=list)  # Track error patterns


class SessionStore:
    """
    Thread-safe in-memory session store.
    
    Manages conversation sessions with history for multi-turn
    interactions with the English teacher.
    """
    
    _sessions: Dict[str, Session] = {}
    _lock = threading.Lock()
    
    @classmethod
    def get_or_create(cls, session_id: str) -> Session:
        """
        Get an existing session or create a new one.
        
        Args:
            session_id: Unique session identifier
            
        Returns:
            Session object
        """
        with cls._lock:
            # Lazy cleanup of old sessions (1% chance to run on read, or always run on write/create? 
            # Let's run it if we're creating a new one to keep it simple and effective enough)
            if session_id not in cls._sessions:
                cls._cleanup_old_sessions()
                cls._sessions[session_id] = Session(id=session_id)
            return cls._sessions[session_id]

    @classmethod
    def _cleanup_old_sessions(cls, max_age_hours: int = 24) -> None:
        """
        Remove sessions older than max_age_hours.
        
        Args:
            max_age_hours: Maximum age of a session in hours
        """
        from datetime import timedelta
        
        now = datetime.now()
        threshold = timedelta(hours=max_age_hours)
        
        # Collect IDs to remove to avoid modifying dict while iterating
        to_remove = []
        for sid, session in cls._sessions.items():
            # Check last interaction time if available, else creation time
            last_active = session.created
            if session.history:
                try:
                    # Try to parse the timestamp of the last message
                    last_msg = session.history[-1]
                    if "ts" in last_msg:
                        last_active = datetime.fromisoformat(last_msg["ts"])
                except (ValueError, KeyError):
                    pass
            
            if now - last_active > threshold:
                to_remove.append(sid)
        
        for sid in to_remove:
            del cls._sessions[sid]
            
        if to_remove:
            # Simple print for now, could be logging
            # print(f"Cleaned up {len(to_remove)} expired sessions.")
            pass
    
    @classmethod
    def add_exchange(
        cls,
        session_id: str,
        user_text: str,
        response: Any,
    ) -> None:
        """
        Add a conversation exchange to the session history.
        
        Args:
            session_id: Session identifier
            user_text: User's input text
            response: TeachOut response object
        """
        session = cls.get_or_create(session_id)
        
        with cls._lock:
            # Add user message
            session.history.append({
                "role": "user",
                "content": user_text,
                "ts": datetime.now().isoformat(),
            })
            
            # Add assistant response
            response_content = ""
            if hasattr(response, 'reply') and response.reply:
                response_content = response.reply
            if hasattr(response, 'follow_up_question') and response.follow_up_question:
                response_content += f" {response.follow_up_question}"
            
            session.history.append({
                "role": "assistant",
                "content": response_content.strip(),
                "ts": datetime.now().isoformat(),
            })
            
            # Track mistakes for pattern recognition
            if hasattr(response, 'mistakes'):
                for mistake in response.mistakes:
                    if hasattr(mistake, 'frm'):
                        session.mistakes_made.append(mistake.frm)
    
    @classmethod
    def get_history(
        cls,
        session_id: str,
        max_turns: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Get recent conversation history for context.
        
        Args:
            session_id: Session identifier
            max_turns: Maximum number of turns to return (each turn = 2 messages)
            
        Returns:
            List of history messages in chronological order
        """
        session = cls.get_or_create(session_id)
        
        with cls._lock:
            # Return last N turns (N*2 messages since each turn is user+assistant)
            max_messages = max_turns * 2
            return session.history[-max_messages:] if session.history else []
    
    @classmethod
    def get_mistake_patterns(
        cls,
        session_id: str,
        top_n: int = 5,
    ) -> List[str]:
        """
        Get the most common mistakes made in the session.
        
        Args:
            session_id: Session identifier
            top_n: Number of top patterns to return
            
        Returns:
            List of most frequent mistake patterns
        """
        session = cls.get_or_create(session_id)
        
        with cls._lock:
            # Count mistake frequencies
            from collections import Counter
            counts = Counter(session.mistakes_made)
            return [pattern for pattern, _ in counts.most_common(top_n)]
    
    @classmethod
    def clear_session(cls, session_id: str) -> bool:
        """
        Clear a specific session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if session existed and was cleared
        """
        with cls._lock:
            if session_id in cls._sessions:
                del cls._sessions[session_id]
                return True
            return False
    
    @classmethod
    def clear_all(cls) -> int:
        """
        Clear all sessions.
        
        Returns:
            Number of sessions cleared
        """
        with cls._lock:
            count = len(cls._sessions)
            cls._sessions.clear()
            return count
    
    @classmethod
    def format_history_for_prompt(
        cls,
        session_id: str,
        max_turns: int = 3,
    ) -> str:
        """
        Format history as a string suitable for prompt injection.
        
        Args:
            session_id: Session identifier
            max_turns: Maximum turns to include
            
        Returns:
            Formatted history string
        """
        history = cls.get_history(session_id, max_turns)
        
        if not history:
            return ""
        
        lines = ["Previous conversation:"]
        for msg in history:
            role = msg.get("role", "unknown").capitalize()
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        
        return "\n".join(lines)
