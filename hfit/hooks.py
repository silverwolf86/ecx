def post_init_hook(env):
    """Backfill id_biometrico for partners that already have a vat set,
    without overwriting any id_biometrico value that may already exist."""
    env.cr.execute("""
        UPDATE res_partner
        SET id_biometrico = vat
        WHERE (id_biometrico IS NULL OR id_biometrico = '')
        AND vat IS NOT NULL AND vat != ''
    """)
