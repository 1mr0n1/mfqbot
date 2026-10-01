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
    # Local OpenAI-compatible server (LM Studio, Ollama, ...). No key needed.
    "local": {
        "url": os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:1234/v1/chat/completions"),
        "api_key": "local",
    },
}

# Key = short name the bot/users see; id = provider's model id.
# no_think = extra payload that switches reasoning off (faster, and no risk of thoughts leaking into replies).
# vision = accepts image_url content; other models get images replaced by a "[photo]" placeholder.
MODELS = {
    "qwen": {"provider": "openrouter", "id": "qwen/qwen3.8-27b:free", "name": "Qwen 3.8 27B", "vision": True,
             "no_think": {"reasoning": {"enabled": False}}},
    "nemotron": {"provider": "nvidia", "id": "nvidia/nemotron-3-super-120b-a12b", "name": "Nemotron 3 Super 120B",
                 "no_think": {"chat_template_kwargs": {"enable_thinking": False}}},
    "omni": {"provider": "nvidia", "id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
             "name": "Nemotron 3 Nano Omni (sees images)", "vision": True,
             "no_think": {"chat_template_kwargs": {"enable_thinking": False}}},
    "local": {"provider": "local", "id": os.getenv("LOCAL_MODEL", "gemma-4-e4b-it-mlx"),
              "name": "Gemma 4 E4B (local)", "vision": True},
}
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen")

SYSTEM_PROMPT = "You are a helpful, friendly assistant. Answer concisely and clearly."
MAX_HISTORY_MESSAGES = 20  # user+assistant messages kept per user
MAX_TOKENS = 2048  # reasoning models spend part of this on thinking
