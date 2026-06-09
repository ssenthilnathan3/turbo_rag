import frappe

def get_settings():
	return frappe.get_single("TurboVec Settings")

def get_ollama_url():
	try:
		settings = get_settings()
		return settings.ollama_url.rstrip('/')
	except Exception:
		return "http://localhost:11434"
