-- Oila Hamyon - SQLite sxemasi
-- Hamma pul summalari INTEGER, eng kichik birlikda (tiyin / sent). 1 so'm = 100.

CREATE TABLE IF NOT EXISTS families (
    id                 INTEGER PRIMARY KEY,
    name               TEXT    NOT NULL DEFAULT 'Oila',
    base_currency      TEXT    NOT NULL DEFAULT 'UZS',
    invite_code        TEXT,
    daily_report       INTEGER NOT NULL DEFAULT 1,
    daily_report_time  TEXT    NOT NULL DEFAULT '21:00',
    monthly_report     INTEGER NOT NULL DEFAULT 1,
    notify_members     INTEGER NOT NULL DEFAULT 1,
    created_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS members (
    id                 INTEGER PRIMARY KEY,
    family_id          INTEGER NOT NULL REFERENCES families(id),
    tg_id              INTEGER NOT NULL UNIQUE,
    name               TEXT    NOT NULL,
    role               TEXT    NOT NULL DEFAULT '',
    is_admin           INTEGER NOT NULL DEFAULT 0,
    is_active          INTEGER NOT NULL DEFAULT 1,
    default_wallet_id  INTEGER,
    joined_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS wallets (
    id               INTEGER PRIMARY KEY,
    family_id        INTEGER NOT NULL REFERENCES families(id),
    name             TEXT    NOT NULL,
    kind             TEXT    NOT NULL DEFAULT 'cash',      -- cash | card | bank | savings | other
    currency         TEXT    NOT NULL DEFAULT 'UZS',
    owner_member_id  INTEGER REFERENCES members(id),
    is_default       INTEGER NOT NULL DEFAULT 0,
    is_archived      INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (family_id, name)
);

CREATE TABLE IF NOT EXISTS categories (
    id           INTEGER PRIMARY KEY,
    family_id    INTEGER NOT NULL REFERENCES families(id),
    key          TEXT    NOT NULL,
    name         TEXT    NOT NULL,
    emoji        TEXT    NOT NULL DEFAULT '•',
    kind         TEXT    NOT NULL,                         -- expense | income
    hints        TEXT    NOT NULL DEFAULT '',
    sort         INTEGER NOT NULL DEFAULT 100,
    is_archived  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (family_id, key)
);

-- Bitta xabar (matn / ovoz / chek) = bitta "paket". Bekor qilish paket bo'yicha ishlaydi.
CREATE TABLE IF NOT EXISTS batches (
    id              INTEGER PRIMARY KEY,
    family_id       INTEGER NOT NULL REFERENCES families(id),
    member_id       INTEGER REFERENCES members(id),
    source          TEXT    NOT NULL DEFAULT 'text',       -- text | voice | photo | recurring | manual
    raw_text        TEXT,
    transcript      TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    deleted_at      TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    id                INTEGER PRIMARY KEY,
    family_id         INTEGER NOT NULL REFERENCES families(id),
    batch_id          INTEGER REFERENCES batches(id),
    kind              TEXT    NOT NULL CHECK (kind IN (
                          'expense','income','transfer','debt_give','debt_take',
                          'debt_repay_in','debt_repay_out','adjustment')),
    amount            INTEGER NOT NULL,          -- tranzaksiya valyutasida, minor
    currency          TEXT    NOT NULL DEFAULT 'UZS',
    rate              TEXT    NOT NULL DEFAULT '1',  -- 1 birlik valyuta = rate asosiy valyutada
    amount_base       INTEGER NOT NULL,          -- asosiy valyutada (so'm), minor
    wallet_id         INTEGER REFERENCES wallets(id),
    wallet_amount     INTEGER,                   -- hamyon valyutasida, minor (adjustment uchun ishorali)
    to_wallet_id      INTEGER REFERENCES wallets(id),
    to_wallet_amount  INTEGER,
    category_id       INTEGER REFERENCES categories(id),
    member_id         INTEGER REFERENCES members(id),   -- kimning harajati / kirimi
    created_by        INTEGER REFERENCES members(id),
    description       TEXT    NOT NULL DEFAULT '',
    item_key          TEXT,
    quantity          TEXT,
    unit              TEXT,
    counterparty      TEXT,
    debt_id           INTEGER REFERENCES debts(id),
    on_credit         INTEGER NOT NULL DEFAULT 0,
    occurred_on       TEXT    NOT NULL,          -- YYYY-MM-DD
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT,
    deleted_at        TEXT
);
CREATE INDEX IF NOT EXISTS ix_tx_family_date ON transactions (family_id, occurred_on);
CREATE INDEX IF NOT EXISTS ix_tx_batch       ON transactions (batch_id);
CREATE INDEX IF NOT EXISTS ix_tx_debt        ON transactions (debt_id);
CREATE INDEX IF NOT EXISTS ix_tx_item        ON transactions (family_id, item_key);

CREATE TABLE IF NOT EXISTS debts (
    id             INTEGER PRIMARY KEY,
    family_id      INTEGER NOT NULL REFERENCES families(id),
    origin_tx_id   INTEGER REFERENCES transactions(id),
    direction      TEXT    NOT NULL CHECK (direction IN ('lent','borrowed')),  -- lent: bizga qarzdor; borrowed: biz qarzdormiz
    counterparty   TEXT    NOT NULL,
    amount         INTEGER NOT NULL,
    currency       TEXT    NOT NULL DEFAULT 'UZS',
    member_id      INTEGER REFERENCES members(id),
    opened_on      TEXT    NOT NULL,
    due_on         TEXT,
    note           TEXT    NOT NULL DEFAULT '',
    closed_at      TEXT,
    deleted_at     TEXT,
    last_reminded  TEXT,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS budgets (
    id           INTEGER PRIMARY KEY,
    family_id    INTEGER NOT NULL REFERENCES families(id),
    category_id  INTEGER REFERENCES categories(id),   -- NULL = umumiy oylik limit
    amount       INTEGER NOT NULL,                    -- asosiy valyutada, minor
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_budget ON budgets (family_id, IFNULL(category_id, 0));

CREATE TABLE IF NOT EXISTS budget_alerts (
    budget_id  INTEGER NOT NULL,
    period     TEXT    NOT NULL,   -- YYYY-MM
    level      INTEGER NOT NULL,   -- 80 | 100
    PRIMARY KEY (budget_id, period, level)
);

CREATE TABLE IF NOT EXISTS recurring (
    id             INTEGER PRIMARY KEY,
    family_id      INTEGER NOT NULL REFERENCES families(id),
    kind           TEXT    NOT NULL DEFAULT 'expense',
    description    TEXT    NOT NULL,
    amount         INTEGER NOT NULL,
    currency       TEXT    NOT NULL DEFAULT 'UZS',
    category_id    INTEGER REFERENCES categories(id),
    wallet_id      INTEGER REFERENCES wallets(id),
    member_id      INTEGER REFERENCES members(id),
    day_of_month   INTEGER NOT NULL,
    next_due       TEXT    NOT NULL,
    last_reminded  TEXT,
    is_active      INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fx_rates (
    currency  TEXT NOT NULL,
    date      TEXT NOT NULL,
    rate      TEXT NOT NULL,
    PRIMARY KEY (currency, date)
);

-- Tasdiq kutayotgan (shubhali) yozuvlar
CREATE TABLE IF NOT EXISTS pending (
    id          INTEGER PRIMARY KEY,
    family_id   INTEGER NOT NULL,
    member_id   INTEGER NOT NULL,
    payload     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Bot xabari qaysi paketga / tranzaksiyalarga tegishli (javob berib tuzatish uchun)
CREATE TABLE IF NOT EXISTS message_links (
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    batch_id    INTEGER,
    tx_ids      TEXT,          -- vergul bilan, bo'sh bo'lsa butun paket
    pending_id  INTEGER,       -- hali tasdiqlanmagan yozuv
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS job_runs (
    job     TEXT NOT NULL,
    key     TEXT NOT NULL,
    ran_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (job, key)
);

CREATE TABLE IF NOT EXISTS ai_log (
    id          INTEGER PRIMARY KEY,
    member_id   INTEGER,
    purpose     TEXT,
    model       TEXT,
    input       TEXT,
    output      TEXT,
    ok          INTEGER,
    latency_ms  INTEGER,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
