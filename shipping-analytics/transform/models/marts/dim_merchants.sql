with current_merchants as (
    select * from {{ ref('snap_merchants') }}
    where dbt_valid_to is null
),

history as (
    select
        merchant_id,
        count(*) - 1                as plan_or_country_changes,
        min(dbt_valid_from)         as first_seen_at
    from {{ ref('snap_merchants') }}
    group by merchant_id
),

shipments as (
    select
        merchant_id,
        min(created_date)           as first_shipment_date,
        max(created_date)           as last_shipment_date,
        count(*)                    as lifetime_shipments
    from {{ ref('fct_shipments') }}
    group by merchant_id
)

select
    m.merchant_id,
    m.merchant_name,
    m.country,
    m.plan,
    m.signup_date,
    h.plan_or_country_changes,
    s.first_shipment_date,
    s.last_shipment_date,
    coalesce(s.lifetime_shipments, 0)   as lifetime_shipments
from current_merchants as m
left join history as h using (merchant_id)
left join shipments as s using (merchant_id)
