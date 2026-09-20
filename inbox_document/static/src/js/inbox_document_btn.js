import { ListController } from "@web/views/list/list_controller";
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";

export class InboxDocumentListController extends ListController {
    /**
     * Abre el wizard de carga del archivo de claves de acceso del SRI.
     */
    actionAbrirWizardSRI() {
        return this.actionService.doAction({
            name: "Cargar Archivo SRI",
            type: "ir.actions.act_window",
            res_model: "inbox.document.import",
            views: [[false, "form"]],
            target: "new",
        });
    }
}

export const inboxDocumentListView = {
    ...listView,
    Controller: InboxDocumentListController,
    buttonTemplate: "inbox_document.ListView.Buttons",
};

registry.category("views").add("inbox_document_list", inboxDocumentListView);
