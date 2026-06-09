import os
import hashlib
import docx
import pypdf
import frappe

def split_text(text, chunk_size=800, chunk_overlap=150):
	if not text:
		return []
	text = text.replace('\r\n', '\n').replace('\r', '\n')
	paragraphs = text.split('\n')
	chunks = []
	current_chunk = []
	current_len = 0
	
	for para in paragraphs:
		para = para.strip()
		if not para:
			continue
		para_len = len(para)
		if current_len + para_len > chunk_size and current_chunk:
			chunks.append("\n".join(current_chunk))
			overlap_len = 0
			new_chunk = []
			for p in reversed(current_chunk):
				if overlap_len + len(p) <= chunk_overlap:
					new_chunk.insert(0, p)
					overlap_len += len(p)
				else:
					break
			current_chunk = new_chunk
			current_len = sum(len(p) for p in current_chunk)
			
		current_chunk.append(para)
		current_len += para_len
		
	if current_chunk:
		chunks.append("\n".join(current_chunk))
		
	return chunks

def get_document_text(doc, fields_to_index=None):
	text_parts = []
	if fields_to_index:
		fields = [f.strip() for f in fields_to_index.split(',') if f.strip()]
	else:
		fields = ['title', 'subject', 'name', 'description', 'content', 'text_content', 'notes', 'component_notes']
		
	for f in fields:
		if doc.get(f):
			val = doc.get(f)
			if isinstance(val, str):
				if '<' in val and '>' in val:
					from frappe.utils.html_utils import clean_html
					val = clean_html(val)
				text_parts.append(f"{f.replace('_', ' ').title()}: {val}")
	return "\n\n".join(text_parts)

def extract_file_text(file_doc):
	try:
		path = file_doc.get_full_path()
	except AttributeError:
		path = frappe.get_site_path(file_doc.file_url.lstrip("/"))

	if not os.path.exists(path):
		return []

	ext = os.path.splitext(file_doc.file_name or file_doc.file_url)[1].lower()
	chunks_with_pages = []

	if ext == '.pdf':
		try:
			with open(path, 'rb') as f:
				reader = pypdf.PdfReader(f)
				for i, page in enumerate(reader.pages):
					text = page.extract_text()
					if text and text.strip():
						chunks_with_pages.append((i + 1, text.strip()))
		except Exception as e:
			frappe.log_error(f"Error parsing PDF {file_doc.file_name}: {str(e)}", "TurboVec RAG")
	elif ext == '.docx':
		try:
			doc = docx.Document(path)
			full_text = []
			for para in doc.paragraphs:
				if para.text and para.text.strip():
					full_text.append(para.text.strip())
			if full_text:
				chunks_with_pages.append((1, "\n".join(full_text)))
		except Exception as e:
			frappe.log_error(f"Error parsing DOCX {file_doc.file_name}: {str(e)}", "TurboVec RAG")
	elif ext in ['.txt', '.md', '.html', '.json', '.csv']:
		try:
			with open(path, 'r', encoding='utf-8', errors='ignore') as f:
				content = f.read()
				if content and content.strip():
					chunks_with_pages.append((1, content.strip()))
		except Exception as e:
			frappe.log_error(f"Error parsing Text file {file_doc.file_name}: {str(e)}", "TurboVec RAG")
			
	return chunks_with_pages

def get_document_hash(doc, fields_to_index=None, index_attachments=False):
	text_content = get_document_text(doc, fields_to_index)
	hash_str = text_content
	
	if index_attachments:
		files = frappe.get_all("File", filters={
			"attached_to_doctype": doc.doctype,
			"attached_to_name": doc.name,
			"is_folder": 0
		}, fields=["name", "modified"])
		
		for f in files:
			hash_str += f"|{f.name}:{f.modified}"
			
	return hashlib.sha256(hash_str.encode('utf-8')).hexdigest()
