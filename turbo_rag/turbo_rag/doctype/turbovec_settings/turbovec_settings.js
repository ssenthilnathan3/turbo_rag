frappe.ui.form.on('TurboVec Settings', {
	onload: function(frm) {
		// Set button action
		frm.set_query('chat_with_rag', function() {
			// No query for button
		});
	},
	refresh: function(frm) {
		frm.add_custom_button(__('Chat with RAG'), function() {
			open_rag_chat_dialog(frm);
		});
		
		if (frm.page.set_inner_btn_group_area) {
			frm.page.add_inner_button(__('Chat with RAG'), function() {
				open_rag_chat_dialog(frm);
			}, __('Actions'));
		}

		// Also bind the field button in the form
		frm.fields_dict['chat_with_rag'].$input.on('click', function() {
			open_rag_chat_dialog(frm);
		});
	}
});

function open_rag_chat_dialog(frm) {
	// Create dialog
	const d = new frappe.ui.Dialog({
		title: __('TurboVec RAG Assistant'),
		fields: [
			{
				fieldtype: 'HTML',
				fieldname: 'chat_area',
				options: `
					<div class="rag-chat-wrapper" style="display: flex; flex-direction: column; height: 500px; background: #f8f9fa; border-radius: 8px; border: 1px solid #e2e8f0; overflow: hidden; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
						<!-- Messages list -->
						<div class="rag-chat-messages" style="flex: 1; padding: 16px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px;">
							<div class="rag-message assistant" style="display: flex; flex-direction: column; align-self: flex-start; max-width: 85%; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px 12px 12px 0px; padding: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
								<div class="rag-message-sender" style="font-weight: 600; font-size: 11px; color: #475569; margin-bottom: 4px;">RAG Assistant</div>
								<div class="rag-message-text" style="font-size: 13px; color: #1e293b; line-height: 1.5;">Hello! I am your RAG Assistant. Ask me anything about the documents in the allowed apps.</div>
							</div>
						</div>
						
						<!-- Input Area -->
						<div class="rag-chat-input-area" style="padding: 12px; background: #ffffff; border-top: 1px solid #e2e8f0; display: flex; gap: 8px; align-items: center;">
							<textarea class="rag-chat-input" placeholder="${__('Ask a question...')}" style="flex: 1; height: 40px; max-height: 120px; border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px 12px; font-size: 13px; resize: none; outline: none; transition: border-color 0.2s;" rows="1"></textarea>
							<button class="btn btn-primary btn-sm rag-chat-send" style="height: 40px; display: flex; align-items: center; justify-content: center; gap: 6px; padding: 0 16px; font-weight: 500;">
								<span>${__('Send')}</span>
							</button>
						</div>
					</div>
				`
			}
		]
	});
	
	d.show();
	d.$wrapper.find('.modal-dialog').css('max-width', '700px');
	
	const $wrapper = d.get_field('chat_area').$wrapper;
	const $messages = $wrapper.find('.rag-chat-messages');
	const $input = $wrapper.find('.rag-chat-input');
	const $send = $wrapper.find('.rag-chat-send');
	
	// Scroll to bottom helper
	const scrollToBottom = () => {
		$messages.animate({ scrollTop: $messages[0].scrollHeight }, 200);
	};
	
	// Input textarea auto-resize and enter key behavior
	$input.on('input', function() {
		this.style.height = 'auto';
		this.style.height = (this.scrollHeight) + 'px';
	});
	
	$input.on('keydown', function(e) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			$send.trigger('click');
		}
	});
	
	// Send click handler
	$send.on('click', async function() {
		const query = $input.val().trim();
		if (!query) return;
		
		// Disable inputs
		$input.val('').prop('disabled', true);
		$send.prop('disabled', true);
		$input.css('height', '40px');
		
		// Append user message
		$messages.append(`
			<div class="rag-message user" style="display: flex; flex-direction: column; align-self: flex-end; max-width: 85%; background: var(--primary-color, #1a73e8); border-radius: 12px 12px 0px 12px; padding: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
				<div class="rag-message-sender" style="font-weight: 600; font-size: 11px; color: rgba(255,255,255,0.8); margin-bottom: 4px; text-align: right;">You</div>
				<div class="rag-message-text" style="font-size: 13px; color: #ffffff; line-height: 1.5; white-space: pre-wrap;">${frappe.utils.escape_html(query)}</div>
			</div>
		`);
		scrollToBottom();
		
		// Append assistant loader bubble
		const assistantMessageId = 'msg-' + frappe.utils.get_random(8);
		$messages.append(`
			<div class="rag-message assistant" id="${assistantMessageId}" style="display: flex; flex-direction: column; align-self: flex-start; max-width: 85%; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px 12px 12px 0px; padding: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
				<div class="rag-message-sender" style="font-weight: 600; font-size: 11px; color: #475569; margin-bottom: 4px;">RAG Assistant</div>
				<div class="rag-message-text" style="font-size: 13px; color: #1e293b; line-height: 1.5;">
					<span class="rag-loading-dots" style="color: #64748b;">Generating answer...</span>
				</div>
			</div>
		`);
		scrollToBottom();
		
		const $msgText = $messages.find(`#${assistantMessageId} .rag-message-text`);
		
		try {
			// Start streaming request!
			const response = await fetch('/api/method/turbo_rag.turbo_rag.api.stream_query_rag', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					'X-Frappe-CSRF-Token': frappe.csrf_token
				},
				body: JSON.stringify({ query: query })
			});
			
			if (!response.ok) {
				throw new Error('Server returned error status ' + response.status);
			}
			
			const reader = response.body.getReader();
			const decoder = new TextDecoder("utf-8");
			let fullAnswer = "";
			let sourcesHtml = "";
			
			// Clear loading state
			$msgText.empty();
			
			while (true) {
				const { value, done } = await reader.read();
				if (done) break;
				
				const text = decoder.decode(value, { stream: true });
				
				// Handle potential split SSE lines
				const lines = text.split("\n\n");
				for (const line of lines) {
					if (!line.trim()) continue;
					
					if (line.startsWith("__SOURCES__:")) {
						try {
							const sourcesStr = line.substring(12);
							const sources = JSON.parse(sourcesStr);
							if (sources && sources.length > 0) {
								sourcesHtml = `
									<div class="rag-message-sources" style="margin-top: 10px; padding-top: 8px; border-top: 1px dashed #cbd5e1; font-size: 11px; color: #64748b;">
										<div style="font-weight: 600; margin-bottom: 4px;">Sources:</div>
										<div style="display: flex; flex-direction: column; gap: 4px;">
											${sources.map((s, idx) => `
												<a href="${s.url}" style="color: var(--primary-color, #1a73e8); text-decoration: none; display: inline-flex; align-items: center; gap: 4px;">
													[${idx + 1}] ${s.source_doctype}: ${s.source_docname} ${s.file_name ? `(${s.file_name})` : ''}
												</a>
											`).join('')}
										</div>
									</div>
								`;
							}
						} catch (e) {
							console.error("Error parsing sources:", e);
						}
					} else {
						fullAnswer += line;
						const htmlAnswer = frappe.utils.escape_html(fullAnswer).replace(/\n/g, '<br>');
						$msgText.html(htmlAnswer + sourcesHtml);
						scrollToBottom();
					}
				}
			}
			
		} catch (error) {
			console.error("RAG Query Error:", error);
			$msgText.html(`<span style="color: #ef4444;">Error: ${error.message || 'Failed to connect to the assistant.'}</span>`);
		} finally {
			// Re-enable inputs
			$input.prop('disabled', false).trigger('focus');
			$send.prop('disabled', false);
		}
	});
}
