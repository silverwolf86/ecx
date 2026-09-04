def migrate(cr, version):
    """Backfill id_biometrico for existing partners on module upgrade,
    without overwriting any id_biometrico value that may already exist."""
    cr.execute("""
        UPDATE res_partner
        SET id_biometrico = vat
        WHERE (id_biometrico IS NULL OR id_biometrico = '')
        AND vat IS NOT NULL AND vat != ''
    """)
