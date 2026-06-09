import os
import frappe
from turbovec import IdMapIndex

def get_settings():
	return frappe.get_single("TurboVec Settings")

def get_index_path():
	settings = get_settings()
	file_path = settings.get("index_file_path") or "private/files/turbovec_index.tvim"
	return frappe.get_site_path(file_path)

def load_index():
	path = get_index_path()
	settings = get_settings()
	dim = int(settings.get("embedding_dim") or 768)
	bit_width = int(settings.get("bit_width") or 4)
	
	if os.path.exists(path) and os.path.getsize(path) > 0:
		try:
			return IdMapIndex.load(path)
		except Exception as e:
			frappe.log_error(f"Error loading index from {path}: {str(e)}. Re-creating...", "TurboVec RAG")
			
	os.makedirs(os.path.dirname(path), exist_ok=True)
	index = IdMapIndex(dim=dim, bit_width=bit_width)
	index.write(path)
	return index

def save_index(index):
	path = get_index_path()
	os.makedirs(os.path.dirname(path), exist_ok=True)
	index.write(path)
