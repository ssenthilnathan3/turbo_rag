# Re-expose all indexing functions for backward compatibility with hooks and background tasks
from .vector_store import load_index, save_index, get_index_path, get_settings
from .chunker import split_text, get_document_text, extract_file_text, get_document_hash
from .sync_manager import (
	index_document,
	index_document_batch,
	delete_document_from_index,
	sync_doctype_index,
	sync_all_indexes,
	rebuild_all_indexes,
	is_doctype_app_allowed,
	is_document_allowed,
	get_eligible_documents
)
from .document_hooks import on_doc_update, on_doc_delete
