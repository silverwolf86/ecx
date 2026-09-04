"""
Tests para verificar que la renovación de suscripciones copia los campos
de tarjeta de crédito (cc_brand_id, cc_cardholdername, expiration_date,
cc_number, cc_number_stored) desde la orden original a la nueva orden de
renovación.

Ejecución:
    python odoo-bin -d <DB> --test-enable --stop-after-init -u hfit
    # o solo este módulo de tests:
    python odoo-bin -d <DB> --test-enable --stop-after-init -u hfit \
        --test-tags /hfit.TestSubscriptionRenewalCCFields
"""

from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase


class TestSubscriptionRenewalCCFields(TransactionCase):
    """
    Verifica que _prepare_upsell_renew_order_values, cuando se invoca
    para una renovación (subscription_state='2_renewal'), añade los
    campos CC al dict de valores de la nueva orden.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Partner de prueba
        cls.partner = cls.env.ref('base.res_partner_1')

        # Marca de tarjeta (credit.card.brand viene de creditcard_subscription)
        cls.brand = cls.env['credit.card.brand'].search([], limit=1)
        if not cls.brand:
            cls.brand = cls.env['credit.card.brand'].create({'name': 'Visa Test', 'code': 'V1'})

        # Plan de suscripción
        cls.plan = cls.env['sale.subscription.plan'].search([], limit=1)
        if not cls.plan:
            cls.plan = cls.env['sale.subscription.plan'].create({
                'name': 'Mensual Test',
                'billing_period_value': 1,
                'billing_period_unit': 'month',
            })

    def _make_subscription(self, **extra):
        """Crea una sale.order con campos CC y la devuelve."""
        vals = {
            'partner_id': self.partner.id,
            'plan_id': self.plan.id,
            'subscription_state': '3_progress',
            'is_subscription': True,
            'start_date': fields.Date.today(),
            'next_invoice_date': fields.Date.today(),
            'cc_brand_id': self.brand.id,
            'cc_cardholdername': 'Juan Pérez',
            'expiration_date': '2027-12-31',
            'cc_number': '4111111111111111',
            'cc_number_stored': '4111111111111111',
        }
        vals.update(extra)
        return self.env['sale.order'].create(vals)

    # ------------------------------------------------------------------
    # Test 1 — Unit test (mock del super para aislar nuestro override)
    # ------------------------------------------------------------------
    def test_renewal_values_include_cc_fields(self):
        """
        El override añade cc_brand_id, cc_cardholdername, expiration_date,
        cc_number y cc_number_stored al dict de valores de renovación.
        """
        order = self._make_subscription()

        # Parcheamos el método del padre para devolver un dict mínimo
        # y así aislar únicamente el comportamiento de nuestro override.
        base_values = {
            'partner_id': order.partner_id.id,
            'subscription_state': '2_renewal',
            'is_subscription': True,
        }
        SaleOrderModel = type(order)
        parent_method = None
        for cls in SaleOrderModel.__mro__[1:]:
            if '_prepare_upsell_renew_order_values' in cls.__dict__:
                parent_method = cls._prepare_upsell_renew_order_values
                break

        with patch.object(parent_method.__objclass__ if hasattr(parent_method, '__objclass__') else SaleOrderModel.__mro__[1],
                          '_prepare_upsell_renew_order_values',
                          return_value=dict(base_values)):
            values = order._prepare_upsell_renew_order_values('2_renewal')

        self.assertEqual(values.get('cc_brand_id'), self.brand.id,
                         "cc_brand_id debe copiarse en la renovación")
        self.assertEqual(values.get('cc_cardholdername'), 'Juan Pérez',
                         "cc_cardholdername debe copiarse en la renovación")
        self.assertEqual(values.get('expiration_date'), '2027-12-31',
                         "expiration_date debe copiarse en la renovación")
        self.assertEqual(values.get('cc_number'), '4111111111111111',
                         "cc_number debe copiarse en la renovación")
        self.assertEqual(values.get('cc_number_stored'), '4111111111111111',
                         "cc_number_stored debe copiarse en la renovación")

    def test_upsell_does_not_copy_cc_fields(self):
        """
        Para upsell (subscription_state='7_upsell') NO se deben copiar
        los campos CC (la lógica sólo aplica en renovación).
        """
        order = self._make_subscription()

        base_values = {
            'partner_id': order.partner_id.id,
            'subscription_state': '7_upsell',
        }
        SaleOrderModel = type(order)
        parent_cls = SaleOrderModel.__mro__[1]

        with patch.object(parent_cls, '_prepare_upsell_renew_order_values',
                          return_value=dict(base_values)):
            values = order._prepare_upsell_renew_order_values('7_upsell')

        self.assertNotIn('cc_brand_id', values,
                         "cc_brand_id NO debe incluirse en un upsell")
        self.assertNotIn('cc_cardholdername', values,
                         "cc_cardholdername NO debe incluirse en un upsell")

    def test_renewal_empty_cc_fields(self):
        """
        Si la orden original no tiene campos CC, los valores en el dict
        deben ser False (no causar KeyError ni crash).
        """
        order = self._make_subscription(
            cc_brand_id=False,
            cc_cardholdername=False,
            expiration_date=False,
            cc_number=False,
            cc_number_stored=False,
        )

        base_values = {'partner_id': order.partner_id.id}
        SaleOrderModel = type(order)
        parent_cls = SaleOrderModel.__mro__[1]

        with patch.object(parent_cls, '_prepare_upsell_renew_order_values',
                          return_value=dict(base_values)):
            values = order._prepare_upsell_renew_order_values('2_renewal')

        self.assertFalse(values.get('cc_brand_id'))
        self.assertFalse(values.get('cc_cardholdername'))
        self.assertFalse(values.get('expiration_date'))
        self.assertFalse(values.get('cc_number'))
        self.assertFalse(values.get('cc_number_stored'))
