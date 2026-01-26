"""
Cache Helper - Text correction caching for English Teacher.

Caches text corrections to avoid redundant LLM calls for identical inputs.
Audio is regenerated for fresh tone variation.
"""
from __future__ import annotations

import hashlib
import threading
from typing import Dict, Optional, Any
from datetime import datetime, timedelta


class CorrectionCache:
    """
    In-memory cache for text corrections.
    
    Caches the text-based corrections (without audio) to speed up
    repeated queries. Audio is regenerated each time for natural variation.
    """
    
    _cache: Dict[str, dict] = {}
    _lock = threading.Lock()
    _max_size = 1000  # Maximum cache entries
    _ttl_hours = 24   # Time-to-live in hours
    
    @classmethod
    def get_key(cls, text: str, mode: str) -> str:
        """
        Generate a cache key from text and mode.
        
        Args:
            text: Input text
            mode: Teaching mode (coach/strict/correct)
            
        Returns:
            MD5 hash key
        """
        normalized = text.strip().lower()
        return hashlib.md5(f"{normalized}:{mode}".encode()).hexdigest()
    
    @classmethod
    def get(cls, text: str, mode: str) -> Optional[Any]:
        """
        Get a cached correction if available and not expired.
        
        Args:
            text: Input text
            mode: Teaching mode
            
        Returns:
            Cached TeachOut object (without audio_path) or None
        """
        key = cls.get_key(text, mode)
        
        with cls._lock:
            if key not in cls._cache:
                return None
            
            entry = cls._cache[key]
            
            # Check TTL
            if datetime.now() - entry["ts"] > timedelta(hours=cls._ttl_hours):
                del cls._cache[key]
                return None
            
            return entry["response"]
    
    @classmethod
    def set(cls, text: str, mode: str, response: Any) -> None:
        """
        Cache a correction response.
        
        The response is stored without audio_path since audio
        should be regenerated for natural variation.
        
        Args:
            text: Input text
            mode: Teaching mode
            response: TeachOut response to cache
        """
        key = cls.get_key(text, mode)
        
        with cls._lock:
            # Evict old entries if at max size
            if len(cls._cache) >= cls._max_size:
                cls._evict_oldest()
            
            # Create a copy without audio_path
            if hasattr(response, 'model_copy'):
                cached_response = response.model_copy()
                cached_response.audio_path = None
            else:
                # Fallback for non-Pydantic objects
                cached_response = response
            
            cls._cache[key] = {
                "response": cached_response,
                "ts": datetime.now(),
            }
    
    @classmethod
    def _evict_oldest(cls) -> None:
        """Evict the oldest cache entries (25% of max size)."""
        # Sort by timestamp and remove oldest 25%
        sorted_entries = sorted(
            cls._cache.items(),
            key=lambda x: x[1]["ts"]
        )
        evict_count = len(cls._cache) // 4
        for key, _ in sorted_entries[:evict_count]:
            del cls._cache[key]
    
    @classmethod
    def clear(cls) -> int:
        """
        Clear all cached entries.
        
        Returns:
            Number of entries cleared
        """
        with cls._lock:
            count = len(cls._cache)
            cls._cache.clear()
            return count
    
    @classmethod
    def stats(cls) -> dict:
        """
        Get cache statistics.
        
        Returns:
            Dict with size, max_size, and ttl_hours
        """
        with cls._lock:
            return {
                "size": len(cls._cache),
                "max_size": cls._max_size,
                "ttl_hours": cls._ttl_hours,
            }
