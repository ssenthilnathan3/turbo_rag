import os
import json
import numpy as np
import frappe

from .vector_store import load_index, save_index, get_index_path, get_settings
from .chunker import split_text, get_document_text, extract_file_text, get_document_hash
from ..ollama_client import get_embeddings

def is_doctype_app_allowed(doctype):
	"""
	Verifies if the DocType belongs to an allowed app in TurboVec Settings.
	"""
	try:
		settings = get_settings()
		allowed_apps_val = settings.get("allowed_apps")
	except Exception:
		return True # Safeguard during migration when table/field doesn't exist
		
	if not allowed_apps_val:
		return True
		
	allowed_apps = [a.strip() for a in allowed_apps_val.split(',') if a.strip()]
	
	module_name = frappe.db.get_value("DocType", doctype, "module")
	if not module_name:
		return False
		
	app_name = frappe.db.get_value("Module Def", module_name, "app_name")
	if not app_name:
		return False
		
	return app_name in allowed_apps

def is_document_allowed(app_index, docname):
	"""
	Checks if a document name/record should be indexed based on filters.
	"""
	if app_index.get("ingest_all") is None or app_index.get("ingest_all") == 1:
		return True
		
	specific_docs_val = app_index.get("specific_documents")
	if specific_docs_val:
		specific_docs = [d.strip() for d in specific_docs_val.split(',') if d.strip()]
		if docname in specific_docs:
			return True
			
	doc_filter_val = app_index.get("document_filter")
	if doc_filter_val:
		try:
			filters = json.loads(doc_filter_val)
			filters["name"] = docname
			exists = frappe.db.exists(app_index.document_type, filters)
			if exists:
				return True
		except Exception as e:
			frappe.log_error(f"Error parsing document filter for {app_index.document_type}: {str(e)}", "TurboVec RAG Ingestion Filter")
			
	return False

def get_eligible_documents(app_index):
	"""
	Returns the list of eligible document records based on configurations.
	"""
	doctype = app_index.document_type
	if app_index.get("ingest_all") is None or app_index.get("ingest_all") == 1:
		return frappe.get_all(doctype, fields=["name"])
		
	eligible_names = set()
	
	specific_docs_val = app_index.get("specific_documents")
	if specific_docs_val:
		specific_docs = [d.strip() for d in specific_docs_val.split(',') if d.strip()]
		existing = frappe.get_all(doctype, filters={"name": ["in", specific_docs]}, fields=["name"])
		for e in existing:
			eligible_names.add(e.name)
			
	doc_filter_val = app_index.get("document_filter")
	if doc_filter_val:
		try:
			filters = json.loads(doc_filter_val)
			matched = frappe.get_all(doctype, filters=filters, fields=["name"])
			for m in matched:
				eligible_names.add(m.name)
		except Exception as e:
			frappe.log_error(f"Error parsing document filter for {doctype}: {str(e)}", "TurboVec RAG Ingestion Filter")
			
	return [{"name": name} for name in eligible_names]

def index_document(doctype, docname, force=False):
	if not is_doctype_app_allowed(doctype):
		return

	try:
		app_index = frappe.get_doc("TurboVec App Index", doctype)
		if not app_index.enabled:
			return
	except frappe.DoesNotExistError:
		return

	if not is_document_allowed(app_index, docname):
		delete_document_from_index(doctype, docname)
		return

	try:
		doc = frappe.get_doc(doctype, docname)
	except frappe.DoesNotExistError:
		delete_document_from_index(doctype, docname)
		return

	current_hash = get_document_hash(doc, app_index.text_fields, app_index.index_attachments)
	
	existing = frappe.get_all("TurboVec Chunk", filters={
		"source_doctype": doctype,
		"source_docname": docname
	}, fields=["name", "hash"])
	
	if existing and not force:
		if existing[0].hash == current_hash:
			return

	delete_document_from_index(doctype, docname)

	chunks_to_save = []
	
	doc_text = get_document_text(doc, app_index.text_fields)
	if doc_text:
		field_chunks = split_text(doc_text)
		for idx, text in enumerate(field_chunks):
			chunks_to_save.append({
				"text": text,
				"page": 1,
				"file": None,
				"index": idx
			})

	if app_index.index_attachments:
		files = frappe.get_all("File", filters={
			"attached_to_doctype": doctype,
			"attached_to_name": docname,
			"is_folder": 0
		}, fields=["name", "file_name", "file_url"])
		
		for f in files:
			file_doc = frappe.get_doc("File", f.name)
			file_pages = extract_file_text(file_doc)
			for page_num, page_text in file_pages:
				page_chunks = split_text(page_text)
				for idx, text in enumerate(page_chunks):
					chunks_to_save.append({
						"text": f"File: {file_doc.file_name} (Page {page_num})\n\n{text}",
						"page": page_num,
						"file": file_doc.name,
						"index": idx
					})

	if not chunks_to_save:
		return

	index = load_index()
	
	max_vector_id = frappe.db.sql("select max(vector_id) from `tabTurboVec Chunk`")[0][0]
	next_vector_id = int((max_vector_id or 0) + 1)
	
	vector_ids = []
	embeddings = []
	
	for chunk in chunks_to_save:
		db_chunk = frappe.get_doc({
			"doctype": "TurboVec Chunk",
			"vector_id": next_vector_id,
			"source_doctype": doctype,
			"source_docname": docname,
			"source_file": chunk["file"],
			"chunk_index": chunk["index"],
			"page_number": chunk["page"],
			"hash": current_hash,
			"text_content": chunk["text"],
			"token_count": len(chunk["text"].split()) 
		})
		db_chunk.insert(ignore_permissions=True)
		
		embedding = get_embeddings([chunk["text"]])[0]
		
		vector_ids.append(next_vector_id)
		embeddings.append(embedding)
		
		next_vector_id += 1
		
	if embeddings:
		embeddings_arr = np.array(embeddings, dtype=np.float32)
		ids_arr = np.array(vector_ids, dtype=np.uint64)
		index.add_with_ids(embeddings_arr, ids_arr)
		save_index(index)

def index_document_batch(doctype, docnames, force=False):
	for docname in docnames:
		try:
			index_document(doctype, docname, force=force)
		except Exception as e:
			frappe.log_error(f"Error indexing document {doctype} {docname} in batch: {str(e)}", "TurboVec RAG")

def delete_document_from_index(doctype, docname):
	chunks = frappe.get_all("TurboVec Chunk", filters={
		"source_doctype": doctype,
		"source_docname": docname
	}, fields=["name", "vector_id"])
	
	if not chunks:
		return

	index = load_index()
	
	modified = False
	for chunk in chunks:
		try:
			index.remove(int(chunk.vector_id))
			modified = True
		except Exception:
			pass
		
		frappe.delete_doc("TurboVec Chunk", chunk.name, force=1, ignore_permissions=True)
		
	if modified:
		save_index(index)

def sync_doctype_index(doctype, force=False):
	"""
	Syncs a single doctype incrementally, respecting filters.
	"""
	if not is_doctype_app_allowed(doctype):
		return {"status": "skipped", "message": f"DocType {doctype} belongs to an app that is not in the allowed apps config."}

	try:
		app_index = frappe.get_doc("TurboVec App Index", doctype)
		if not app_index.enabled:
			return {"status": "skipped", "message": f"DocType {doctype} is disabled in RAG configuration."}
	except frappe.DoesNotExistError:
		return {"status": "error", "message": f"DocType {doctype} is not configured in RAG."}

	db_docs = get_eligible_documents(app_index)
	db_doc_names = {d["name"] for d in db_docs}

	chunk_docs = frappe.get_all("TurboVec Chunk", 
		filters={"source_doctype": doctype}, 
		fields=["source_docname", "hash"]
	)
	chunk_doc_info = {c.source_docname: c.hash for c in chunk_docs}

	deleted_docs = [name for name in chunk_doc_info if name not in db_doc_names]
	for name in deleted_docs:
		delete_document_from_index(doctype, name)

	to_index = []
	for name in db_doc_names:
		if name not in chunk_doc_info:
			to_index.append(name)
		else:
			if force:
				to_index.append(name)
			else:
				doc = frappe.get_doc(doctype, name)
				current_hash = get_document_hash(doc, app_index.text_fields, app_index.index_attachments)
				if current_hash != chunk_doc_info[name]:
					to_index.append(name)

	batch_size = 50
	if len(to_index) > batch_size:
		for i in range(0, len(to_index), batch_size):
			batch = to_index[i:i+batch_size]
			frappe.enqueue(
				"turbo_rag.turbo_rag.index_manager.index_document_batch",
				queue="long",
				doctype=doctype,
				docnames=batch,
				force=force
			)
		return {
			"status": "enqueued",
			"deleted_count": len(deleted_docs),
			"to_index_count": len(to_index),
			"message": f"Enqueued {len(to_index)} docs in batches of {batch_size} for {doctype}."
		}
	else:
		indexed_count = 0
		for name in to_index:
			index_document(doctype, name, force=force)
			indexed_count += 1
			
		return {
			"status": "success",
			"deleted_count": len(deleted_docs),
			"indexed_count": indexed_count,
			"message": f"Sync completed. Indexed: {indexed_count}, Deleted from index: {len(deleted_docs)}."
		}

def sync_all_indexes(force=False):
	"""
	Syncs all enabled doctypes incrementally.
	"""
	app_indexes = frappe.get_all("TurboVec App Index", filters={"enabled": 1}, fields=["document_type"])
	
	results = {}
	for app in app_indexes:
		res = sync_doctype_index(app.document_type, force=force)
		results[app.document_type] = res
		
	return results

def rebuild_all_indexes():
	"""
	Legacy method to truncate everything and do a clean rebuilt, respecting allowed apps.
	"""
	frappe.db.sql("truncate table `tabTurboVec Chunk`")
	
	path = get_index_path()
	if os.path.exists(path):
		os.remove(path)
		
	index = load_index()
	
	app_indexes = frappe.get_all("TurboVec App Index", filters={"enabled": 1}, fields=["document_type"])
	
	total_docs = 0
	for app in app_indexes:
		doctype = app.document_type
		if not is_doctype_app_allowed(doctype):
			continue
			
		docs = get_eligible_documents(app)
		for d in docs:
			index_document(doctype, d["name"], force=True)
			total_docs += 1
			
	return total_docs
