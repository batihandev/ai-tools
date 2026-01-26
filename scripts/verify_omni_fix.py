
from scripts.helper.env import load_repo_dotenv
load_repo_dotenv()

import os
import sys

# Mock imports/env if needed
os.environ["OMNI_MODEL"] = os.getenv("OMNI_MODEL", "Qwen/Qwen2.5-Omni-3B")

print("Testing _load_model with fix...")
try:
    from scripts.helper.omni_helper import _load_model
    model, processor = _load_model()
    print("SUCCESS: Model and processor loaded.")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"FAILURE: {e}")
    sys.exit(1)
