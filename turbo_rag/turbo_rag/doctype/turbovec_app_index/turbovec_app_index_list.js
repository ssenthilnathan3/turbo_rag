frappe.listview_settings['TurboVec App Index'] = {
	onload: function(listview) {
		listview.page.add_inner_button(__('Ingest All Module DocTypes'), function() {
			frappe.prompt([
				{
					label: __('Module Name'),
					fieldname: 'module_name',
					fieldtype: 'Link',
					options: 'Module Def',
					reqd: 1
				}
			], function(values) {
				frappe.call({
					method: 'turbo_rag.turbo_rag.doctype.turbovec_app_index.turbovec_app_index.ingest_module_doctypes',
					args: {
						module_name: values.module_name
					},
					freeze: true,
					freeze_message: __('Registering and Syncing Module DocTypes...'),
					callback: function(r) {
						if (r.message && r.message.status === 'success') {
							frappe.show_alert({
								message: r.message.message,
								indicator: 'green'
							});
							listview.refresh();
						}
					}
				});
			}, __('Ingest All DocTypes of a Module'), __('Ingest'));
		});
	}
};
