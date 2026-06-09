import frappe
from frappe import _
import numpy as np
import json
import werkzeug.wrappers

from .ollama_client import get_embeddings, chat_completion
from .index_manager import load_index, rebuild_all_indexes, sync_doctype_index, sync_all_indexes

@frappe.whitelist()
def query_rag(query, top_k=None):
	"""
	Retrieves context documents from TurboVec, filters them by role permission,
	and passes permitted context to Ollama to generate a source-attributed answer.
	"""
	if not query:
		frappe.throw(_("Query text is required"))
		
	settings = frappe.get_single("TurboVec Settings")
	top_k_retrieve = int(settings.top_k_retrieve or 50)
	top_k_final = int(top_k or settings.top_k_final or 5)
	similarity_threshold = float(settings.similarity_threshold or 0.0)
	
	# 1. Embed query
	try:
		query_emb = get_embeddings([query])[0]
	except Exception as e:
		frappe.log_error(f"Error embedding query: {str(e)}", "TurboVec RAG")
		return {
			"answer": f"Error generating embeddings for the query. Please verify that Ollama is running and the embedding model is loaded.",
			"sources": []
		}
		
	# 2. Search index
	try:
		index = load_index()
		if len(index) == 0:
			return {
				"answer": "The RAG index is currently empty. Please index some documents or ask a System Manager to sync the indexes.",
				"sources": []
			}
		
		# search needs 2D array: (nq, dim)
		queries_arr = np.array([query_emb], dtype=np.float32)
		scores, ids = index.search(queries_arr, k=top_k_retrieve)
		
		scores_list = scores[0]
		ids_list = ids[0]
	except Exception as e:
		frappe.log_error(f"Error searching vector index: {str(e)}", "TurboVec RAG")
		return {
			"answer": "Error searching the vector index.",
			"sources": []
		}

	# 3. Retrieve chunks from DB and check permissions
	candidates = []
	for score, vector_id in zip(scores_list, ids_list):
		if score < similarity_threshold:
			continue
			
		chunk_data = frappe.db.get_value(
			"TurboVec Chunk",
			{"vector_id": int(vector_id)},
			["source_doctype", "source_docname", "source_file", "page_number", "text_content"],
			as_dict=1
		)
		
		if not chunk_data:
			continue
			
		# Role authorization checks: check if the user has READ permission to the source document
		if frappe.has_permission(chunk_data.source_doctype, "read", chunk_data.source_docname):
			file_name = None
			if chunk_data.source_file:
				file_name = frappe.db.get_value("File", chunk_data.source_file, "file_name")
				
			# Format desk URL
			dt_slug = chunk_data.source_doctype.lower().replace("_", "-")
			desk_url = f"/app/{dt_slug}/{chunk_data.source_docname}"
			
			candidates.append({
				"source_doctype": chunk_data.source_doctype,
				"source_docname": chunk_data.source_docname,
				"source_file": chunk_data.source_file,
				"file_name": file_name,
				"page_number": chunk_data.page_number,
				"text_content": chunk_data.text_content,
				"score": float(score),
				"url": desk_url
			})

	# Take top k permitted chunks
	permitted_chunks = candidates[:top_k_final]
	
	if not permitted_chunks:
		return {
			"answer": "I found no documents matching your query that you have permissions to view.",
			"sources": []
		}

	# 4. Construct Prompt
	context_parts = []
	for idx, chunk in enumerate(permitted_chunks):
		source_info = f"Source [{idx+1}]: {chunk['source_doctype']} - {chunk['source_docname']}"
		if chunk.get('file_name'):
			source_info += f" (File: {chunk['file_name']}, Page: {chunk['page_number']})"
		context_parts.append(f"{source_info}\nContent:\n{chunk['text_content']}")
		
	context = "\n\n---\n\n".join(context_parts)
	
	system_prompt = f"""You are a secure, helpful assistant for a Frappe custom ERP application. 
Answer the user's question using ONLY the provided context blocks below. 
Each block represents a document the user is authorized to read.
If the answer cannot be found in the context blocks, say "I cannot find the answer in the provided documents." 
Do not make up facts or use external knowledge. Always keep your response professional and cite your sources (e.g. "According to Source [1]...").

Context:
{context}
"""
	
	user_prompt = f"Question: {query}"
	
	# 5. Generate completion
	answer = chat_completion(user_prompt, system_prompt)
	
	return {
		"answer": answer,
		"sources": [
			{
				"source_doctype": c["source_doctype"],
				"source_docname": c["source_docname"],
				"file_name": c["file_name"],
				"page_number": c["page_number"],
				"score": c["score"],
				"url": c["url"],
				"preview": c["text_content"][:200] + "..." if len(c["text_content"]) > 200 else c["text_content"]
			} for c in permitted_chunks
		]
	}

@frappe.whitelist()
def sync_rag(doctype=None, force=False):
	"""
	Exposes incremental sync functionality via API.
	If doctype is given, syncs only that doctype.
	Otherwise, syncs all enabled doctypes incrementally.
	"""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only System Managers can trigger index synchronization"), frappe.PermissionError)
		
	# Check force argument type (might come as string 'true' / 'false' from HTTP calls)
	is_forced = str(force).lower() in ["true", "1"]
	
	if doctype:
		# Run sync for specific doctype
		res = sync_doctype_index(doctype, force=is_forced)
		return {"status": "success", "results": {doctype: res}}
	else:
		# Run sync for all doctypes
		res = sync_all_indexes(force=is_forced)
		return {"status": "success", "results": res}

@frappe.whitelist()
def trigger_rebuild():
	"""
	Legacy method to trigger a complete wipe and rebuild of RAG indexes.
	We recommend using sync_rag instead to minimize overhead.
	"""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only System Managers can rebuild the RAG indexes"), frappe.PermissionError)
		
	frappe.enqueue(
		"turbo_rag.turbo_rag.index_manager.rebuild_all_indexes",
		queue="long",
		now=True
	)
	
	return {
		"status": "success",
		"message": _("RAG indexes rebuild started successfully.")
	}



@frappe.whitelist()
def stream_query_rag(query):
	"""
	Generates a streaming response for the query.
	Yields source list first, then stream of text from Ollama.
	"""
	if not query:
		frappe.throw(_("Query text is required"))
		
	settings = frappe.get_single("TurboVec Settings")
	top_k_retrieve = int(settings.top_k_retrieve or 50)
	top_k_final = int(settings.top_k_final or 5)
	similarity_threshold = float(settings.similarity_threshold or 0.0)
	
	# 1. Embed query
	try:
		query_emb = get_embeddings([query])[0]
	except Exception as e:
		frappe.log_error(f"Error embedding query: {str(e)}", "TurboVec RAG")
		def err_gen():
			yield "Error generating embeddings for the query. Please verify that Ollama is running and the embedding model is loaded.".encode('utf-8')
		return werkzeug.wrappers.Response(err_gen(), mimetype='text/plain')
		
	# 2. Search index
	try:
		index = load_index()
		if len(index) == 0:
			def empty_gen():
				yield "The RAG index is currently empty. Please index some documents first.".encode('utf-8')
			return werkzeug.wrappers.Response(empty_gen(), mimetype='text/plain')
		
		queries_arr = np.array([query_emb], dtype=np.float32)
		scores, ids = index.search(queries_arr, k=top_k_retrieve)
		scores_list = scores[0]
		ids_list = ids[0]
	except Exception as e:
		frappe.log_error(f"Error searching vector index: {str(e)}", "TurboVec RAG")
		def search_err_gen():
			yield "Error searching the vector index.".encode('utf-8')
		return werkzeug.wrappers.Response(search_err_gen(), mimetype='text/plain')

	# 3. Retrieve chunks from DB and check permissions
	candidates = []
	for score, vector_id in zip(scores_list, ids_list):
		if score < similarity_threshold:
			continue
			
		chunk_data = frappe.db.get_value(
			"TurboVec Chunk",
			{"vector_id": int(vector_id)},
			["source_doctype", "source_docname", "source_file", "page_number", "text_content"],
			as_dict=1
		)
		
		if not chunk_data:
			continue
			
		if frappe.has_permission(chunk_data.source_doctype, "read", chunk_data.source_docname):
			file_name = None
			if chunk_data.source_file:
				file_name = frappe.db.get_value("File", chunk_data.source_file, "file_name")
				
			dt_slug = chunk_data.source_doctype.lower().replace("_", "-")
			desk_url = f"/app/{dt_slug}/{chunk_data.source_docname}"
			
			candidates.append({
				"source_doctype": chunk_data.source_doctype,
				"source_docname": chunk_data.source_docname,
				"source_file": chunk_data.source_file,
				"file_name": file_name,
				"page_number": chunk_data.page_number,
				"text_content": chunk_data.text_content,
				"score": float(score),
				"url": desk_url
			})

	permitted_chunks = candidates[:top_k_final]
	
	# Prepare sources metadata outside generator
	sources_data = [
		{
			"source_doctype": c["source_doctype"],
			"source_docname": c["source_docname"],
			"file_name": c["file_name"],
			"page_number": c["page_number"],
			"score": c["score"],
			"url": c["url"]
		} for c in permitted_chunks
	]
	
	# Construct Prompt outside generator
	context_parts = []
	for idx, chunk in enumerate(permitted_chunks):
		source_info = f"Source [{idx+1}]: {chunk['source_doctype']} - {chunk['source_docname']}"
		if chunk.get('file_name'):
			source_info += f" (File: {chunk['file_name']}, Page: {chunk['page_number']})"
		context_parts.append(f"{source_info}\nContent:\n{chunk['text_content']}")
		
	context = "\n\n---\n\n".join(context_parts)
	
	system_prompt = f"""You are a secure, helpful assistant for a Frappe custom ERP application. 
Answer the user's question using ONLY the provided context blocks below. 
Each block represents a document the user is authorized to read.
If the answer cannot be found in the context blocks, say "I cannot find the answer in the provided documents." 
Do not make up facts or use external knowledge. Always keep your response professional and cite your sources (e.g. "According to Source [1]...").

Context:
{context}
"""
	user_prompt = f"Question: {query}"
	
	ollama_url = f"{settings.ollama_url.rstrip('/')}/api/chat"
	model = settings.llm_model or "llama3.1"
	
	messages = [
		{"role": "system", "content": system_prompt},
		{"role": "user", "content": user_prompt}
	]
	
	# Generate streaming response
	def response_generator():
		# 1. Yield sources
		yield f"__SOURCES__:{json.dumps(sources_data)}\n\n".encode('utf-8')
		
		if not permitted_chunks:
			yield "I found no documents matching your query that you have permissions to view.".encode('utf-8')
			return

		# 2. Hit Ollama and stream response
		import requests
		try:
			response = requests.post(ollama_url, json={
				"model": model,
				"messages": messages,
				"stream": True
			}, stream=True, timeout=300)
			
			for line in response.iter_lines():
				if line:
					chunk = json.loads(line.decode('utf-8'))
					content = chunk.get("message", {}).get("content", "")
					if content:
						yield content.encode('utf-8')
		except Exception as e:
			yield f"\n[Error communicating with Ollama: {str(e)}]".encode('utf-8')

	resp = werkzeug.wrappers.Response(response_generator(), mimetype='text/event-stream')
	resp.headers['Cache-Control'] = 'no-cache'
	resp.headers['Connection'] = 'keep-alive'
	resp.headers['X-Accel-Buffering'] = 'no'
	return resp
