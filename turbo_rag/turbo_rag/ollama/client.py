# Re-expose all Ollama functions for backward compatibility
from .config import get_settings, get_ollama_url
from .embeddings import get_embeddings
from .chat import chat_completion
