#!/usr/bin/env python3
"""
Model Downloader for Qwen2.5-Omni Audio Models.

Downloads the Qwen2.5-Omni model from HuggingFace for voice-to-voice.
Run: python -m scripts.download_audio_models
Or: make model-audio

Requires HF_TOKEN for gated models.
"""
from __future__ import annotations

import os
import sys

def main():
    from .helper.env import load_repo_dotenv
    load_repo_dotenv()

    try:
        from huggingface_hub import snapshot_download, login
    except ImportError:
        print("huggingface_hub not installed. Run 'pip install huggingface_hub'", file=sys.stderr)
        sys.exit(1)

    hf_token = os.getenv("HF_TOKEN")
    if hf_token:
        print("Authenticating with HuggingFace...")
        try:
            login(token=hf_token)
        except Exception as e:
            print(f"Warning: Failed to login with HF_TOKEN: {e}", file=sys.stderr)
    else:
        print("Note: HF_TOKEN not set. Some models may require authentication.")
        print("  Get a token from: https://huggingface.co/settings/tokens")
        print()

    # Model to download (Qwen2.5-Omni for voice-to-voice)
    # See: https://huggingface.co/Qwen/Qwen2.5-Omni-3B
    model_id = os.getenv("OMNI_MODEL", "Qwen/Qwen2.5-Omni-3B")

    print(f"Downloading model: {model_id}")
    print("This may take a while for large models...")
    print()

    try:
        path = snapshot_download(
            repo_id=model_id,
            token=hf_token,
            resume_download=True,
            # allow_patterns=["*.json", "*.bin", "*.safetensors", "*.model"], # Optional optimization
        )
        print(f"✓ Model downloaded to: {path}")
    except Exception as e:
        print(f"✗ Download failed: {e}", file=sys.stderr)
        err_str = str(e).lower()
        if "gated" in err_str or "access" in err_str or "401" in err_str or "403" in err_str:
            print("\nThis model may require accepting terms on HuggingFace or a valid token.", file=sys.stderr)
            print(f"Visit: https://huggingface.co/{model_id}", file=sys.stderr)
        elif "connect" in err_str or "timeout" in err_str:
             print("\nNetwork error. Please check your connection and try again.", file=sys.stderr)
        sys.exit(1)

    print()
    print("Done! You can now use voice-to-voice features.")


if __name__ == "__main__":
    main()
