import frappe
from .sync_manager import is_doctype_app_allowed, is_document_allowed

def on_doc_update(doc, method=None):
	"""
	Hook called whenever a document is updated.
	"""
	if doc.doctype in ["TurboVec Settings", "TurboVec App Index", "TurboVec Chunk"]:
		return

	try:
		if not is_doctype_app_allowed(doc.doctype):
			return

		# Safe check during schema migration or first-time setup
		if not frappe.db.exists("DocType", "TurboVec App Index"):
			return

		if not frappe.db.exists("TurboVec App Index", doc.doctype):
			return

		app_index = frappe.get_doc("TurboVec App Index", doc.doctype)
		if not app_index.get("enabled"):
			return
	except Exception:
		return # Silence errors during migrations or bootstrap

	if is_document_allowed(app_index, doc.name):
		frappe.enqueue(
			"turbo_rag.turbo_rag.index_manager.index_document",
			queue="long",
			doctype=doc.doctype,
			docname=doc.name,
			force=False,
			now=frappe.flags.in_test
		)
	else:
		frappe.enqueue(
			"turbo_rag.turbo_rag.index_manager.delete_document_from_index",
			queue="long",
			doctype=doc.doctype,
			docname=doc.name,
			now=frappe.flags.in_test
		)

def on_doc_delete(doc, method=None):
	"""
	Hook called when a document is trashed/deleted.
	"""
	if doc.doctype in ["TurboVec Settings", "TurboVec App Index", "TurboVec Chunk"]:
		return

	try:
		if not is_doctype_app_allowed(doc.doctype):
			return

		# Safe check during schema migration or first-time setup
		if not frappe.db.exists("DocType", "TurboVec App Index"):
			return

		if not frappe.db.exists("TurboVec App Index", doc.doctype):
			return
	except Exception:
		return # Silence errors during migrations or bootstrap

	frappe.enqueue(
		"turbo_rag.turbo_rag.index_manager.delete_document_from_index",
		queue="long",
		doctype=doc.doctype,
		docname=doc.name,
		now=frappe.flags.in_test
	)
