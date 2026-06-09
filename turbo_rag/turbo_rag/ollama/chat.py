import requests
import frappe
from .config import get_settings, get_ollama_url

def chat_completion(prompt, system_prompt=None):
	"""
	Call Ollama chat endpoint with system prompt and user query.
	"""
	settings = get_settings()
	url = f"{get_ollama_url()}/api/chat"
	model = settings.llm_model or "llama3.1"
	
	messages = []
	if system_prompt:
		messages.append({"role": "system", "content": system_prompt})
	messages.append({"role": "user", "content": prompt})
	
	try:
		response = requests.post(url, json={
			"model": model,
			"messages": messages,
			"stream": False
		}, timeout=300)
		
		if response.status_code == 200:
			return response.json()["message"]["content"]
		else:
			frappe.msgprint(f"Ollama LLM Error: {response.text}")
			return f"Error contacting Ollama: {response.text}"
	except Exception as e:
		frappe.log_error(f"Ollama chat error: {str(e)}", "TurboVec RAG")
		return f"Error connecting to Ollama at {url}. Make sure Ollama is running and the model {model} is installed."
