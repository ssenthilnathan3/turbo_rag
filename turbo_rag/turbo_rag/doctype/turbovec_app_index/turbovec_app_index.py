import frappe
from frappe.model.document import Document

class TurboVecAppIndex(Document):
	pass

@frappe.whitelist()
def ingest_module_doctypes(module_name):
	"""
	Automatically registers and triggers ingestion for all eligible DocTypes in a given module.
	"""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(frappe._("Only System Managers can run this action"), frappe.PermissionError)

	if not module_name:
		frappe.throw(frappe._("Module Name is required"))

	# Find all non-child, non-single, non-virtual DocTypes belonging to this module
	doctypes = frappe.get_all("DocType", filters={
		"module": module_name,
		"istable": 0,
		"issingle": 0,
		"is_virtual": 0
	}, pluck="name")

	if not doctypes:
		return {"status": "success", "message": f"No eligible DocTypes found in module {module_name}."}

	created_count = 0
	for dt in doctypes:
		if not frappe.db.exists("TurboVec App Index", dt):
			# Get a list of text fields on the DocType as defaults to index
			meta = frappe.get_meta(dt)
			text_fields = [
				f.fieldname for f in meta.fields 
				if f.fieldtype in ["Data", "Text", "Long Text", "Small Text", "Code", "Text Editor"]
			]
			# Default to name plus first 8 text fields
			text_fields_str = ",".join(text_fields[:8])

			doc = frappe.get_doc({
				"doctype": "TurboVec App Index",
				"document_type": dt,
				"enabled": 1,
				"ingest_all": 1,
				"text_fields": text_fields_str
			})
			doc.insert(ignore_permissions=True)
			created_count += 1
		else:
			# Enable if already exists but disabled
			doc = frappe.get_doc("TurboVec App Index", dt)
			if not doc.enabled:
				doc.enabled = 1
				doc.save(ignore_permissions=True)

	# Queue the sync job for each of the doctypes
	for dt in doctypes:
		frappe.enqueue(
			"turbo_rag.turbo_rag.index_manager.sync_doctype_index",
			queue="long",
			doctype=dt,
			force=False
		)

	return {
		"status": "success",
		"message": f"Registered {created_count} new DocTypes and queued sync for all {len(doctypes)} DocTypes in module '{module_name}'."
	}
