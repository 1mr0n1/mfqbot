import os

from dotenv import load_dotenv

load_dotenv()

# Each provider exposes an OpenAI-compatible /chat/completions endpoint.
PROVIDERS = {
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "api_key": os.environ["OPENROUTER_API_KEY"],
    },
    "nvidia": {
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "api_key": os.environ["NVIDIA_API_KEY"],
    },
}

# Key = short name the bot/users see; id = provider's model id.
MODELS = {
    "qwen": {"provider": "openrouter", "id": "qwen/qwen3.8-27b:free", "name": "Qwen 3.8 27B"},
    "nemotron": {"provider": "nvidia", "id": "nvidia/nemotron-3-super-120b-a12b", "name": "Nemotron 3 Super 120B"},
}
DEFAULT_MODEL = "qwen"

SYSTEM_PROMPT = "You are a helpful, friendly assistant. Answer concisely and clearly."
MAX_HISTORY_MESSAGES = 20  # user+assistant messages kept per user
MAX_TOKENS = 2048  # reasoning models spend part of this on thinking
