from pathlib import Path


REVISION_FILE = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260802_0001_initial.py"
)


def test_initial_revision_exists_and_is_root_revision():
    source = REVISION_FILE.read_text(encoding="utf-8")
    assert 'revision: str = "20260802_0001"' in source
    assert 'down_revision: Union[str, Sequence[str], None] = None' in source
    for table in ("users", "sessions", "categories", "payment_methods", "transactions"):
        assert f'"{table}"' in source


def test_partner_revision_is_additive_and_preserves_legacy_partner_reference():
    revision_file = REVISION_FILE.parent / "20260802_0002_partners.py"
    source = revision_file.read_text(encoding="utf-8")
    assert 'revision: str = "20260802_0002"' in source
    assert 'down_revision: Union[str, Sequence[str], None] = "20260802_0001"' in source
    assert 'op.create_table(\n        "partners"' in source
    assert 'op.create_table(\n        "partner_ledger"' in source
    # Existing transactions.partner_id remains nullable and is not rewritten
    # with a FK, allowing legacy ids to survive the phase-three migration.
    assert "transactions.partner_id" in source


def test_settlement_revision_adds_daily_snapshot_head():
    revision_file = REVISION_FILE.parent / "20260804_0004_settlements.py"
    source = revision_file.read_text(encoding="utf-8")
    assert 'revision: str = "20260804_0004_settlements"' in source
    assert 'down_revision: Union[str, Sequence[str], None] = "20260803_0003_ai"' in source
    assert 'op.create_table(\n        "daily_snapshots"' in source
    assert '"uq_daily_snapshots_user_date"' in source


def test_settlement_revision_is_the_current_additive_head():
    revision_file = REVISION_FILE.parent / "20260804_0004_settlements.py"
    source = revision_file.read_text(encoding="utf-8")
    assert 'revision: str = "20260804_0004_settlements"' in source
    assert 'down_revision: Union[str, Sequence[str], None] = "20260803_0003_ai"' in source
    assert 'op.create_table(\n        "daily_snapshots"' in source
    for column in (
        '"settlement_date"',
        '"income_cents"',
        '"expense_cents"',
        '"total_assets_cents"',
        '"account_balances"',
        '"account_changes"',
    ):
        assert column in source
    assert "uq_daily_snapshots_user_date" in source


def test_partner_website_revision_preserves_legacy_email_column_and_only_backfills_urls():
    revision_file = REVISION_FILE.parent / "20260805_0006_partner_website.py"
    source = revision_file.read_text(encoding="utf-8")
    assert 'revision: str = "20260805_0006_partner_website"' in source
    assert 'down_revision: Union[str, Sequence[str], None] = "20260805_0005_salary_category"' in source
    assert 'op.add_column("partners"' in source
    assert 'sa.Column("website"' in source
    assert 'lower(trim(email)) LIKE \'https://%\'' in source
    assert 'op.drop_column("partners", "website")' in source
    # The migration must retain the old column rather than renaming/dropping
    # it, so old clients and historical email values remain readable.
    assert "email" in source


def test_financial_account_revision_adds_roles_and_transfer_columns():
    revision_file = REVISION_FILE.parent / "20260806_0007_financial_accounts.py"
    source = revision_file.read_text(encoding="utf-8")
    assert 'revision: str = "20260806_0007_financial_accounts"' in source
    assert 'down_revision: Union[str, Sequence[str], None] = "20260805_0006_partner_website"' in source
    assert 'op.add_column(\n        "payment_methods"' in source
    assert '"account_role"' in source
    assert '"kind"' in source
    assert '"transfer_payment_method_id"' in source
    assert "category_id" in source and "nullable=True" in source


def test_salary_category_revision_is_idempotent_and_non_destructive():
    revision_file = REVISION_FILE.parent / "20260805_0005_salary_category.py"
    source = revision_file.read_text(encoding="utf-8")
    assert 'revision: str = "20260805_0005_salary_category"' in source
    assert 'down_revision: Union[str, Sequence[str], None] = "20260804_0004_settlements"' in source
    assert "'工资收入'" in source
    assert "'income'" in source
    assert "WHERE NOT EXISTS" in source
    # A downgrade must not delete a category a user may have edited after the
    # migration ran.
    assert "def downgrade()" in source
    assert "pass" in source[source.index("def downgrade()"):]


def test_all_accounts_balance_revision_backfills_before_enabling_tracking():
    revision_file = REVISION_FILE.parent / "20260807_0009_all_accounts_track_balance.py"
    source = revision_file.read_text(encoding="utf-8")
    assert 'revision: str = "20260807_0009_balances"' in source
    assert 'down_revision: Union[str, Sequence[str], None] = "20260806_0008_ai_fallback_config"' in source
    assert "WHERE pm.track_balance = FALSE" in source
    assert "t.status = 'normal'" in source
    assert "t.transfer_payment_method_id = pm.id" in source
    assert "track_balance = TRUE" in source
