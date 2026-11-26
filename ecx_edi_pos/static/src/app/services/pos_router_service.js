import { PosRouter } from "@point_of_sale/app/services/pos_router_service";
import { patch } from "@web/core/utils/patch";

patch(PosRouter.prototype, {
    // @Override
    // In standard Odoo, closing the session reloads /pos/ui/<config_id>, which shows the
    // "Open Session" screen again and users tend to reopen it by mistake. `close()` is only
    // called from the closing popup, so we send the user back to the backend instead
    // (same target as the "Backend" button).
    close() {
        window.location.href = "/odoo/action-point_of_sale.action_client_pos_menu";
    },
});
