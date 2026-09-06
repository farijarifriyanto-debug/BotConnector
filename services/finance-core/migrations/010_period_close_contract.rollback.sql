BEGIN;

DROP TRIGGER IF EXISTS
    trg_finance_guard_fiscal_period_state
ON fiscal_periods;

DROP FUNCTION IF EXISTS
    finance_guard_fiscal_period_state();

DROP TRIGGER IF EXISTS
    trg_finance_guard_journal_period_integrity
ON journal_entries;

DROP FUNCTION IF EXISTS
    finance_guard_journal_period_integrity();

DROP FUNCTION IF EXISTS
    finance_close_fiscal_period(uuid);

COMMIT;
