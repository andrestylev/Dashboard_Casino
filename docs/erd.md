# Database diagram

> Generated from the models by `python api/scripts/generate_erd.py`. Do not edit by hand.

How to read the crow's feet: look at the symbol **next to the other table**.
`||` exactly one, `|o` zero or one, `o{` zero or many, `o|` zero or one (one-to-one side).

```mermaid
erDiagram
  admin_users ||--o{ admin_recovery_codes : admin_user_id
  admin_users ||--o{ admin_sessions : admin_user_id
  roles ||--o{ admin_users : role_id
  admin_users |o--o{ audit_log : admin_user_id
  game_sessions ||--o{ bets : session_id
  players ||--o{ bonuses : player_id
  transactions |o--o| bonuses : transaction_id
  games ||--o{ game_sessions : game_id
  players ||--o{ game_sessions : player_id
  game_categories ||--o{ games : category_id
  admin_users ||--o{ player_notes : admin_user_id
  players ||--o{ player_notes : player_id
  admin_users |o--o{ risk_alerts : assigned_to_admin_id
  players ||--o{ risk_alerts : player_id
  admin_users |o--o{ transactions : created_by_admin_id
  wallets ||--o{ transactions : player_id
  players ||--o| wallets : player_id
  games ||--o{ daily_game_stats : "game_id (view)"
  admin_recovery_codes {
    bigint id PK
    bigint admin_user_id FK
    varchar code_hash
    timestamptz used_at
    timestamptz created_at
  }
  admin_sessions {
    uuid id PK
    bigint admin_user_id FK
    varchar token_hash UK
    timestamptz created_at
    timestamptz expires_at
    timestamptz revoked_at
    inet ip_address
    varchar user_agent
  }
  admin_users {
    bigint id PK
    varchar email UK
    varchar password_hash
    varchar full_name
    smallint role_id FK
    bool is_active
    varchar totp_secret
    bool totp_enabled
    int failed_login_attempts
    timestamptz locked_until
    timestamptz last_login_at
    timestamptz created_at
    timestamptz updated_at
  }
  audit_log {
    bigint id PK
    bigint admin_user_id FK
    varchar action
    varchar resource_type
    varchar resource_id
    jsonb details
    inet ip_address
    timestamptz created_at
  }
  bets {
    bigint id PK
    bigint session_id FK
    numeric stake
    numeric payout
    timestamptz placed_at
    bool is_win
  }
  bonuses {
    bigint id PK
    bigint player_id FK
    enum type
    enum status
    numeric amount
    numeric wagering_multiplier
    numeric wagered_amount
    timestamptz granted_at
    timestamptz expires_at
    timestamptz completed_at
    bigint transaction_id FK, UK
  }
  game_categories {
    smallint id PK
    varchar code UK
    varchar name
  }
  game_sessions {
    bigint id PK
    bigint player_id FK
    int game_id FK
    timestamptz started_at
    timestamptz ended_at
    enum device_type
    inet ip_address
    varchar country_code
    varchar device_fingerprint
  }
  games {
    int id PK
    smallint category_id FK
    varchar name UK
    varchar provider
    numeric theoretical_rtp
    enum volatility
    numeric min_bet
    numeric max_bet
    bool is_active
    date released_at
  }
  player_notes {
    bigint id PK
    bigint player_id FK
    bigint admin_user_id FK
    text note
    timestamptz created_at
  }
  players {
    bigint id PK
    varchar username UK
    varchar email UK
    varchar first_name
    varchar last_name
    date birth_date
    varchar country_code
    enum status
    enum kyc_status
    enum vip_tier
    enum registration_channel
    timestamptz registered_at
    timestamptz last_login_at
    timestamptz self_exclusion_until
    numeric deposit_limit_monthly
    numeric loss_limit_monthly
    timestamptz updated_at
  }
  risk_alerts {
    bigint id PK
    bigint player_id FK
    enum alert_type
    enum severity
    enum status
    bigint assigned_to_admin_id FK
    jsonb details
    timestamptz created_at
    timestamptz updated_at
    timestamptz resolved_at
    text resolution_note
  }
  roles {
    smallint id PK
    varchar name UK
    varchar description
  }
  transactions {
    bigint id PK
    bigint player_id FK
    enum type
    enum status
    numeric amount
    enum method
    timestamptz created_at
    timestamptz completed_at
    varchar external_ref UK
    bigint created_by_admin_id FK
    varchar note
    inet ip_address
  }
  wallets {
    bigint player_id PK, FK
    numeric balance
    timestamptz updated_at
  }
  daily_game_stats {
    date stat_date
    int game_id
    int total_bets
    int unique_players
    numeric total_staked
    numeric total_paid
    numeric ggr
  }
```

## Conventions

- Identifiers: `bigint` identity keys (small lookup tables use `smallint`/`int`).
- Money: `numeric(12,2)`; wallet balance `numeric(14,2)`.
  One currency for the whole casino (not stored per row).
- Timestamps: `timestamptz`, UTC.
- Enumerations: `varchar` + CHECK constraint (easier to migrate than native PostgreSQL enums).
- `players` and `admin_users` are never deleted (deactivate/close instead); financial and gameplay
  foreign keys are `ON DELETE RESTRICT`.
- `daily_game_stats` is a **materialized view** over `bets`; refresh it with
  `REFRESH MATERIALIZED VIEW CONCURRENTLY daily_game_stats;`.
- Wallet is optional at the database level (`players ||--o| wallets`): the application creates one
  wallet per player.

