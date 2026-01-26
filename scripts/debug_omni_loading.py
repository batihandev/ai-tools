
from scripts.helper.env import load_repo_dotenv
load_repo_dotenv()

import os
from transformers import AutoConfig

model_id = os.getenv("OMNI_MODEL", "Qwen/Qwen2.5-Omni-3B")
print(f"Loading config for: {model_id}")

try:
    config = AutoConfig.from_pretrained(model_id, trust_remote_code=True)
    print("Main Config loaded successfully.")
    
    if hasattr(config, "talker_config"):
        print("Talker config found.")
        talker_config = config.talker_config
        if hasattr(talker_config, "pad_token_id"):
            print(f"pad_token_id found: {talker_config.pad_token_id}")
        else:
            print("ERROR: pad_token_id NOT found in talker_config!")
    else:
        print("Talker config NOT found in main config.")
        
except Exception as e:
    print(f"Error loading config: {e}")
