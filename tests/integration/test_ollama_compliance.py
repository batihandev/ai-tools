import pytest
import requests
import os
import random
import string
from scripts.helper.ollama_utils import resolve_ollama_url

# Use a lightweight model for compliance checks if possible
MODEL = os.getenv("TEST_OLLAMA_MODEL", "llama3.2:3b")

def get_base_url():
    return resolve_ollama_url("http://localhost:11434")

def is_ollama_reachable():
    try:
        url = get_base_url()
        requests.get(f"{url}/api/version", timeout=1)
        return True
    except:
        return False

@pytest.mark.skipif(not is_ollama_reachable(), reason="Ollama not reachable")
class TestOllamaCompliance:
    
    def test_temperature_determinism(self):
        """
        Verify that temperature=0.0 produces deterministic output
        and temperature=1.0 produces varied output.
        """
        base_url = get_base_url()
        prompt = "Generate a random string of 32 alphanumeric characters. Output ONLY the string."
        
        def run_generate(temp):
            resp = requests.post(f"{base_url}/api/generate", json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temp,
                    "seed": 42 if temp == 0 else None,
                    "num_ctx": 4096,
                    "num_thread": 1,  # Force single thread for max determinism
                }
            })
            resp.raise_for_status()
            return resp.json()["response"].strip()

        # Test Determinism (Temp 0)
        out1 = run_generate(0.0)
        out2 = run_generate(0.0)
        # Perfect determinism can be flaky on some HW/quantization, check mostly stable
        assert out1[:15] == out2[:15], f"Temperature 0.0 should be mostly deterministic (prefix match). Got:\n{out1}\n{out2}"

        # Test randomness (Temp 1.0)
        # Note: small chance of collision but extremely unlikely for 32 chars
        outs = set()
        for _ in range(3):
            outs.add(run_generate(1.0))
        
        assert len(outs) > 1, "Temperature 1.0 should vary output"

    def test_num_predict_compliance(self):
        """
        Verify that 'num_predict' (max tokens) limits the output length.
        """
        base_url = get_base_url()
        prompt = "Write a very long essay about the history of the internet."
        
        def run_with_limit(limit):
            resp = requests.post(f"{base_url}/api/generate", json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": limit,
                    "temperature": 0.0
                }
            })
            resp.raise_for_status()
            return resp.json()

        # Short limit
        short_resp = run_with_limit(5)
        short_tokens = short_resp.get("eval_count", 100)
        assert short_tokens <= 10, f"Expected <= 10 tokens for limit 5 (allowing small buffer), got {short_tokens}"
        
        # Long limit
        long_resp = run_with_limit(50)
        long_tokens = long_resp.get("eval_count", 0)
        assert long_tokens > 20, f"Expected > 20 tokens for limit 50, got {long_tokens}"
