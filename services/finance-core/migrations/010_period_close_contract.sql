BEGIN;

-- ============================================================
-- 1. JOURNAL <-> FISCAL PERIOD IDENTITY
-- ============================================================

CREATE OR REPLACE FUNCTION finance_guard_journal_period_integrity()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_period_company uuid;
    v_starts_on date;
    v_ends_on date;
BEGIN
    SELECT
        company_id,
        starts_on,
        ends_on
    INTO
        v_period_company,
        v_starts_on,
        v_ends_on
    FROM fiscal_periods
    WHERE id=NEW.fiscal_period_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'fiscal period not found';
    END IF;

    IF v_period_company <> NEW.company_id THEN
        RAISE EXCEPTION
            'journal company does not match fiscal period company';
    END IF;

    IF NEW.journal_date < v_starts_on
       OR NEW.journal_date > v_ends_on THEN
        RAISE EXCEPTION
            'journal date % is outside fiscal period % to %',
            NEW.journal_date,
            v_starts_on,
            v_ends_on;
    END IF;

    RETURN NEW;
END;
$function$;

CREATE TRIGGER trg_finance_guard_journal_period_integrity
BEFORE INSERT OR
       UPDATE OF company_id,fiscal_period_id,journal_date
ON journal_entries
FOR EACH ROW
EXECUTE FUNCTION finance_guard_journal_period_integrity();

-- ============================================================
-- 2. FISCAL PERIOD STATE MACHINE
-- ============================================================

CREATE OR REPLACE FUNCTION finance_guard_fiscal_period_state()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_close_journal uuid;
BEGIN
    IF TG_OP='DELETE' THEN

        IF EXISTS (
            SELECT 1
            FROM journal_entries
            WHERE fiscal_period_id=OLD.id
        ) THEN
            RAISE EXCEPTION
                'fiscal period with journals cannot be deleted';
        END IF;

        RETURN OLD;
    END IF;

    -- CLOSED is final.
    IF OLD.status='CLOSED' THEN
        RAISE EXCEPTION
            'closed fiscal period is immutable';
    END IF;

    -- Period identity cannot change after accounting activity.
    IF (
           NEW.company_id IS DISTINCT FROM OLD.company_id
        OR NEW.period_year IS DISTINCT FROM OLD.period_year
        OR NEW.period_month IS DISTINCT FROM OLD.period_month
        OR NEW.starts_on IS DISTINCT FROM OLD.starts_on
        OR NEW.ends_on IS DISTINCT FROM OLD.ends_on
    )
    AND EXISTS (
        SELECT 1
        FROM journal_entries
        WHERE fiscal_period_id=OLD.id
    ) THEN

        RAISE EXCEPTION
            'fiscal period identity is immutable after journal activity';
    END IF;

    IF OLD.status='OPEN'
       AND NEW.status='OPEN' THEN

        IF NEW.closed_at IS NOT NULL THEN
            RAISE EXCEPTION
                'open fiscal period cannot have closed_at';
        END IF;

        RETURN NEW;
    END IF;

    IF OLD.status='OPEN'
       AND NEW.status='CLOSED' THEN

        IF NEW.closed_at IS NULL THEN
            RAISE EXCEPTION
                'closed fiscal period requires closed_at';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM journal_entries
            WHERE fiscal_period_id=OLD.id
              AND status='DRAFT'
        ) THEN
            RAISE EXCEPTION
                'fiscal period contains DRAFT journals';
        END IF;

        SELECT id
        INTO v_close_journal
        FROM journal_entries
        WHERE fiscal_period_id=OLD.id
          AND status='POSTED'
          AND source_type='period.close'
          AND source_id=OLD.id::text
        LIMIT 1;

        IF v_close_journal IS NULL THEN
            RAISE EXCEPTION
                'posted period close journal evidence is required';
        END IF;

        RETURN NEW;
    END IF;

    RAISE EXCEPTION
        'invalid fiscal period state transition % -> %',
        OLD.status,
        NEW.status;
END;
$function$;

CREATE TRIGGER trg_finance_guard_fiscal_period_state
BEFORE UPDATE OR DELETE
ON fiscal_periods
FOR EACH ROW
EXECUTE FUNCTION finance_guard_fiscal_period_state();

-- ============================================================
-- 3. ATOMIC PERIOD CLOSE
-- ============================================================

CREATE OR REPLACE FUNCTION finance_close_fiscal_period(
    p_period uuid
)
RETURNS uuid
LANGUAGE plpgsql
AS $function$
DECLARE
    v_period fiscal_periods%ROWTYPE;

    v_close_journal uuid;
    v_retained uuid;

    v_account record;

    v_line integer := 0;

    v_debit numeric(18,2);
    v_credit numeric(18,2);

    v_total_debit numeric(18,2) := 0;
    v_total_credit numeric(18,2) := 0;

    v_retained_debit numeric(18,2) := 0;
    v_retained_credit numeric(18,2) := 0;

    v_remaining numeric(18,2);
BEGIN
    SELECT *
    INTO v_period
    FROM fiscal_periods
    WHERE id=p_period
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'fiscal period not found';
    END IF;

    -- Idempotent replay.
    IF v_period.status='CLOSED' THEN

        SELECT id
        INTO v_close_journal
        FROM journal_entries
        WHERE fiscal_period_id=p_period
          AND status='POSTED'
          AND source_type='period.close'
          AND source_id=p_period::text
        LIMIT 1;

        IF v_close_journal IS NULL THEN
            RAISE EXCEPTION
                'closed period has no canonical close journal';
        END IF;

        RETURN v_close_journal;
    END IF;

    IF v_period.status <> 'OPEN' THEN
        RAISE EXCEPTION
            'unsupported fiscal period status';
    END IF;

    -- No premature production close.
    IF CURRENT_DATE <= v_period.ends_on THEN
        RAISE EXCEPTION
            'fiscal period cannot be closed before period end';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM journal_entries
        WHERE fiscal_period_id=p_period
          AND status='DRAFT'
    ) THEN
        RAISE EXCEPTION
            'fiscal period contains DRAFT journals';
    END IF;

    SELECT id
    INTO v_retained
    FROM accounts
    WHERE company_id=v_period.company_id
      AND system_key='RETAINED_EARNINGS'
      AND type='EQUITY'
      AND normal_balance='CREDIT'
      AND allow_posting=true
      AND active=true;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'retained earnings account not found';
    END IF;

    IF (
        SELECT COUNT(*)
        FROM accounts
        WHERE company_id=v_period.company_id
          AND system_key='RETAINED_EARNINGS'
          AND type='EQUITY'
          AND normal_balance='CREDIT'
          AND allow_posting=true
          AND active=true
    ) <> 1 THEN
        RAISE EXCEPTION
            'retained earnings account must be unique';
    END IF;

    SELECT id
    INTO v_close_journal
    FROM journal_entries
    WHERE company_id=v_period.company_id
      AND journal_number=
          'CLOSE-' ||
          v_period.period_year::text ||
          '-' ||
          lpad(v_period.period_month::text,2,'0')
    LIMIT 1;

    IF v_close_journal IS NOT NULL THEN
        RAISE EXCEPTION
            'period close journal number collision';
    END IF;

    v_close_journal := gen_random_uuid();

    INSERT INTO journal_entries (
        id,
        company_id,
        fiscal_period_id,
        journal_number,
        journal_date,
        description,
        source_system,
        source_type,
        source_id
    )
    VALUES (
        v_close_journal,
        v_period.company_id,
        v_period.id,

        'CLOSE-' ||
        v_period.period_year::text ||
        '-' ||
        lpad(v_period.period_month::text,2,'0'),

        v_period.ends_on,

        'Fiscal period close ' ||
        v_period.period_year::text ||
        '-' ||
        lpad(v_period.period_month::text,2,'0'),

        'finance_core',
        'period.close',
        v_period.id::text
    );

    FOR v_account IN

        SELECT
            a.id,
            a.code,
            a.name,
            a.type,

            CASE
                WHEN a.type='REVENUE'
                THEN COALESCE(
                    SUM(jl.credit-jl.debit)
                    FILTER (WHERE je.id IS NOT NULL),
                    0
                )

                WHEN a.type='EXPENSE'
                THEN COALESCE(
                    SUM(jl.debit-jl.credit)
                    FILTER (WHERE je.id IS NOT NULL),
                    0
                )

                ELSE 0
            END::numeric(18,2) AS balance

        FROM accounts a

        LEFT JOIN journal_lines jl
          ON jl.account_id=a.id

        LEFT JOIN journal_entries je
          ON je.id=jl.journal_entry_id
         AND je.fiscal_period_id=v_period.id
         AND je.status='POSTED'

        WHERE a.company_id=v_period.company_id
          AND a.type IN ('REVENUE','EXPENSE')
          AND a.active=true

        GROUP BY
            a.id,
            a.code,
            a.name,
            a.type

        ORDER BY a.code

    LOOP
        IF v_account.balance = 0 THEN
            CONTINUE;
        END IF;

        v_debit := 0;
        v_credit := 0;

        IF v_account.type='REVENUE' THEN

            IF v_account.balance > 0 THEN
                v_debit := v_account.balance;
            ELSE
                v_credit := -v_account.balance;
            END IF;

        ELSIF v_account.type='EXPENSE' THEN

            IF v_account.balance > 0 THEN
                v_credit := v_account.balance;
            ELSE
                v_debit := -v_account.balance;
            END IF;

        END IF;

        v_line := v_line + 1;

        INSERT INTO journal_lines (
            journal_entry_id,
            line_number,
            account_id,
            description,
            debit,
            credit
        )
        VALUES (
            v_close_journal,
            v_line,
            v_account.id,
            'Period close: ' || v_account.name,
            v_debit,
            v_credit
        );

        v_total_debit :=
            v_total_debit + v_debit;

        v_total_credit :=
            v_total_credit + v_credit;
    END LOOP;

    IF v_total_debit > v_total_credit THEN
        v_retained_credit :=
            v_total_debit - v_total_credit;

    ELSIF v_total_credit > v_total_debit THEN
        v_retained_debit :=
            v_total_credit - v_total_debit;
    END IF;

    IF v_retained_debit <> 0
       OR v_retained_credit <> 0 THEN

        v_line := v_line + 1;

        INSERT INTO journal_lines (
            journal_entry_id,
            line_number,
            account_id,
            description,
            debit,
            credit
        )
        VALUES (
            v_close_journal,
            v_line,
            v_retained,
            'Current earnings transferred to retained earnings',
            v_retained_debit,
            v_retained_credit
        );
    END IF;

    -- Always use canonical posting kernel.
    PERFORM finance_post_journal(v_close_journal);

    -- All nominal accounts must be zero after close.
    SELECT
        COALESCE(SUM(abs(x.balance)),0)
    INTO v_remaining
    FROM (
        SELECT
            a.id,

            CASE
                WHEN a.type='REVENUE'
                THEN COALESCE(
                    SUM(jl.credit-jl.debit)
                    FILTER (WHERE je.id IS NOT NULL),
                    0
                )

                WHEN a.type='EXPENSE'
                THEN COALESCE(
                    SUM(jl.debit-jl.credit)
                    FILTER (WHERE je.id IS NOT NULL),
                    0
                )

                ELSE 0
            END AS balance

        FROM accounts a

        LEFT JOIN journal_lines jl
          ON jl.account_id=a.id

        LEFT JOIN journal_entries je
          ON je.id=jl.journal_entry_id
         AND je.fiscal_period_id=v_period.id
         AND je.status='POSTED'

        WHERE a.company_id=v_period.company_id
          AND a.type IN ('REVENUE','EXPENSE')

        GROUP BY
            a.id,
            a.type
    ) x;

    IF v_remaining <> 0 THEN
        RAISE EXCEPTION
            'nominal accounts did not close to zero: %',
            v_remaining;
    END IF;

    UPDATE fiscal_periods
    SET
        status='CLOSED',
        closed_at=now()
    WHERE id=v_period.id;

    RETURN v_close_journal;
END;
$function$;

COMMIT;
