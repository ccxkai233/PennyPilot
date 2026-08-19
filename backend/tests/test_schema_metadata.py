from app.db import Base
import app.models  # noqa: F401  (register mapped classes)


def test_core_tables_are_registered_for_migrations():
    expected_tables = {"users", "sessions", "categories", "payment_methods", "transactions"}
    assert expected_tables.issubset(Base.metadata.tables)


def test_transaction_uses_integer_cents_and_audit_columns():
    table = Base.metadata.tables["transactions"]

    assert str(table.c.amount_cents.type).upper().startswith("BIGINT")
    assert table.c.kind.nullable is False
    assert table.c.status.nullable is False
    assert table.c.voided_at.nullable is True
    assert table.c.void_reason.nullable is True
    assert table.c.category_id.nullable is True
    assert table.c.category_id.foreign_keys
    assert table.c.payment_method_id.foreign_keys
    assert table.c.transfer_payment_method_id.nullable is True
    assert table.c.transfer_payment_method_id.foreign_keys


def test_payment_methods_support_financial_account_roles():
    table = Base.metadata.tables["payment_methods"]

    assert table.c.account_role.nullable is False


def test_categories_and_payment_methods_have_per_user_uniqueness():
    categories = Base.metadata.tables["categories"]
    payment_methods = Base.metadata.tables["payment_methods"]

    category_constraints = {constraint.name for constraint in categories.constraints}
    payment_constraints = {constraint.name for constraint in payment_methods.constraints}
    assert "uq_categories_user_name_direction" in category_constraints
    assert "uq_payment_methods_user_name" in payment_constraints


def test_partner_profile_keeps_legacy_email_and_adds_website():
    partners = Base.metadata.tables["partners"]
    assert partners.c.website.nullable is True
    assert partners.c.email.nullable is True
