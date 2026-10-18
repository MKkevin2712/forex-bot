-- Tables du journal quand JOURNAL=supabase (à exécuter dans l'éditeur SQL de Supabase).

create table if not exists trades (
    id bigint generated always as identity primary key,
    broker text not null,
    broker_trade_id text not null,
    instrument text not null,
    direction text not null check (direction in ('LONG', 'SHORT')),
    units double precision not null,
    entry_time timestamptz not null,
    entry_price double precision not null,
    stop_loss double precision,
    take_profit double precision,
    risk_amount double precision,
    signal_reason text,
    indicators jsonb,
    status text not null default 'OPEN' check (status in ('OPEN', 'CLOSED')),
    exit_time timestamptz,
    exit_price double precision,
    pnl double precision,
    close_reason text,
    unique (broker, broker_trade_id)
);

create table if not exists equity (
    time timestamptz primary key,
    balance double precision not null,
    nav double precision not null
);

-- Le bot utilise la clé service_role côté serveur : on ferme l'accès public.
alter table trades enable row level security;
alter table equity enable row level security;
