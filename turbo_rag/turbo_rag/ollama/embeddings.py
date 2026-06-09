import requests
import frappe
from .config import get_settings, get_ollama_url

def get_embeddings(texts):
	"""
	Generate embeddings for a list of texts (or a single text) using Ollama.
	Returns list of float vectors.
	"""
	settings = get_settings()
	url = f"{get_ollama_url()}/api/embed"
	model = settings.embedding_model or "nomic-embed-text"
	
	if isinstance(texts, str):
		texts = [texts]
		
	embeddings = []
	for text in texts:
		try:
			response = requests.post(url, json={
				"model": model,
				"input": text
			}, timeout=30)
			
			if response.status_code == 200:
				data = response.json()
				if "embeddings" in data:
					embeddings.extend(data["embeddings"])
				elif "embedding" in data:
					embeddings.append(data["embedding"])
				else:
					fallback_url = f"{get_ollama_url()}/api/embeddings"
					fallback_resp = requests.post(fallback_url, json={
						"model": model,
						"prompt": text
					}, timeout=30)
					if fallback_resp.status_code == 200:
						embeddings.append(fallback_resp.json()["embedding"])
					else:
						raise Exception(f"Failed to generate embedding: {fallback_resp.text}")
			else:
				fallback_url = f"{get_ollama_url()}/api/embeddings"
				fallback_resp = requests.post(fallback_url, json={
					"model": model,
					"prompt": text
				}, timeout=30)
				if fallback_resp.status_code == 200:
					embeddings.append(fallback_resp.json()["embedding"])
				else:
					raise Exception(f"Failed to generate embedding: {response.text}")
		except Exception as e:
			frappe.log_error(f"Ollama embedding error: {str(e)}", "TurboVec RAG")
			dim = int(settings.embedding_dim or 768)
			embeddings.append([0.0] * dim)
			
	return embeddings
