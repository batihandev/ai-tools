"""
Omni Helper - Qwen2.5-Omni voice-to-voice integration.

Uses HuggingFace transformers to load Qwen2.5-Omni for:
- Audio input (ASR/understanding)
- Text + Audio output (LLM + TTS in one model)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional, List, Generator, Any

# Lazy imports to avoid loading heavy deps unless needed
_model = None
_processor = None

DEFAULT_MODEL = "Qwen/Qwen2.5-Omni-3B"


def unload_model():
    """Unload the model to free VRAM/RAM."""
    global _model, _processor
    
    if _model is None:
        return  # Nothing to unload
    
    import gc
    import torch
    
    # Clear references
    _model = None
    _processor = None
    
    # Force garbage collection
    gc.collect()
    
    # Clear CUDA cache if available
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
    
    print("Omni model unloaded. VRAM freed.", file=sys.stderr)


def _load_model(model_id: str = None):
    """Lazily load the Qwen2.5-Omni model and processor."""
    global _model, _processor
    
    if _model is not None:
        return _model, _processor
    
    model_id = model_id or os.getenv("OMNI_MODEL", DEFAULT_MODEL)
    
    try:
        from transformers import Qwen2_5OmniForConditionalGeneration, Qwen2_5OmniProcessor
    except ImportError:
        raise ImportError(
            "transformers not installed or outdated. "
            "Run 'pip install transformers>=4.40 accelerate'"
        )
    
    print(f"Loading Omni model: {model_id}...", file=sys.stderr)
    
    import torch
    from transformers import AutoConfig
    
    # Load config first to patch potential issues (e.g. missing pad_token_id in talker_config)
    try:
        config = AutoConfig.from_pretrained(model_id, trust_remote_code=True)
        
        # Patch for Qwen2.5-Omni: Ensure talker_config has pad_token_id
        if hasattr(config, "talker_config") and not hasattr(config.talker_config, "pad_token_id"):
            pad_id = 0
            setattr(config.talker_config, "pad_token_id", pad_id)
        
        # Note: Qwen2.5-Omni doesn't support bitsandbytes quantization properly
        # (multi-component model with audio encoder + talker + token2wav)
        # Using float16 for best balance of speed and memory
        _model = Qwen2_5OmniForConditionalGeneration.from_pretrained(
            model_id,
            config=config,
            torch_dtype=torch.float16,
            device_map="auto",
            low_cpu_mem_usage=True,
        )
    except Exception as e:
        print(f"Model loading failed: {e}", file=sys.stderr)
        raise

    _processor = Qwen2_5OmniProcessor.from_pretrained(model_id, trust_remote_code=True)
    
    print("Model loaded.", file=sys.stderr)
    return _model, _processor


class OmniHelper:
    """
    Helper for Qwen2.5-Omni voice-to-voice interactions.
    
    This model handles ASR, LLM, and TTS in a single forward pass.
    """
    
    @staticmethod
    def chat_with_audio(
        text: str,
        audio_path: Optional[str] = None,
        persona: str = "",
        output_audio_path: Optional[str] = None,
        history: Optional[List[dict]] = None,
    ) -> dict:
        """
        Send text (and optionally audio) to the model, get text + audio response.
        
        Args:
            text: User's text message
            audio_path: Optional path to audio file for voice input
            persona: Optional persona instruction (e.g., "As an English teacher" - 
                    prepended to user message since custom system prompts break TTS)
            output_audio_path: Where to save the response audio (optional)
            history: Optional conversation history for multi-turn context
                     Each item should have 'role' and 'content' keys
            
        Returns:
            dict with 'text' (response text) and 'audio_path' (if generated)
        """
        model, processor = _load_model()
        
        try:
            from qwen_omni_utils import process_mm_info
            import soundfile as sf
        except ImportError as e:
            raise ImportError(f"Missing dependency: {e}. Run 'pip install qwen_omni_utils soundfile'")
        
        # Qwen2.5-Omni REQUIRES this specific system prompt for TTS audio output
        # Custom system prompts break audio generation
        DEFAULT_SYSTEM_PROMPT = (
            "You are Qwen, a virtual human developed by the Qwen Team, Alibaba Group, "
            "capable of perceiving auditory and visual inputs, as well as generating text and speech."
        )
        
        # Build user content - prepend persona to text if provided
        user_text = text
        if persona:
            user_text = f"[{persona}] {text}"
        
        user_content = []
        if audio_path:
            user_content.append({"type": "audio", "audio": audio_path})
        if user_text:
            user_content.append({"type": "text", "text": user_text})
        
        # Start with REQUIRED system message (do not modify!)
        conversation = [
            {
                "role": "system",
                "content": [{"type": "text", "text": DEFAULT_SYSTEM_PROMPT}],
            },
        ]
        
        # Add conversation history if provided
        if history:
            for msg in history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if content:
                    conversation.append({
                        "role": role,
                        "content": [{"type": "text", "text": content}],
                    })
        
        # Add current user message
        conversation.append({
            "role": "user",
            "content": user_content if user_content else text,
        })
        
        # Process inputs
        text_input = processor.apply_chat_template(
            conversation, add_generation_prompt=True, tokenize=False
        )
        audios, images, videos = process_mm_info(conversation, use_audio_in_video=False)
        
        inputs = processor(
            text=text_input,
            audio=audios,
            images=images,
            videos=videos,
            return_tensors="pt",
            padding=True,
            use_audio_in_video=False,
        )
        inputs = inputs.to(model.device).to(model.dtype)
        
        # Generate response
        text_ids, audio = model.generate(**inputs, use_audio_in_video=False)
        full_response = processor.batch_decode(
            text_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )[0]
        
        # Extract only the assistant's last response (not the full conversation)
        # The full_response contains "system\n...\nuser\n...\nassistant\n..."
        # We only want the text after the last "assistant" marker
        response_text = full_response
        if "\nassistant\n" in full_response:
            response_text = full_response.split("\nassistant\n")[-1].strip()
        elif "assistant\n" in full_response:
            response_text = full_response.split("assistant\n")[-1].strip()
        
        result = {"text": response_text, "audio_path": None}
        
        # Save audio if generated and path provided
        if audio is not None and output_audio_path:
            sf.write(
                output_audio_path,
                audio.reshape(-1).detach().cpu().numpy(),
                samplerate=24000,
            )
            result["audio_path"] = output_audio_path
        
        return result
    
    @staticmethod
    def transcribe(audio_path: str) -> str:
        """
        Transcribe audio to text using the Omni model.
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            Transcribed text
        """
        result = OmniHelper.chat_with_audio(
            text="Please transcribe the audio exactly.",
            audio_path=audio_path,
        )
        return result["text"]
    
    @staticmethod
    def speak(text: str, output_path: str) -> str:
        """
        Convert text to speech using the Omni model.
        
        Args:
            text: Text to speak
            output_path: Where to save the audio file
            
        Returns:
            Path to the generated audio file
        """
        result = OmniHelper.chat_with_audio(
            text=f"Please say the following: {text}",
            output_audio_path=output_path,
        )
        return result.get("audio_path", output_path)
