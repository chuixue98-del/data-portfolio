-- One row per merchant with recent shipping health.
-- Built for Customer Success: synced to the CRM so account managers see who needs a call.
-- Small merchants swing a lot from month to month. Below these volumes a change is
-- more likely noise than a real problem, so the rule does not fire.
{% set min_volume = 50 %}       {# shipments in the previous 30 days, for volume rules #}
{% set min_delivered = 30 %}    {# delivered parcels in the last 30 days, for the on-time rule #}

with as_of as (
    select max(created_date) as as_of_date from {{ ref('fct_shipments') }}
),

shipments as (
    select
        f.*,
        date_diff('day', f.created_date, a.as_of_date) as days_ago
    from {{ ref('fct_shipments') }} as f
    cross join as_of as a
),

per_merchant as (
    select
        merchant_id,
        count(*) filter (where days_ago < 30)                                   as shipments_30d,
        count(*) filter (where days_ago between 30 and 59)                      as shipments_prev_30d,
        count(*) filter (where days_ago < 30 and is_on_time is not null)        as delivered_30d,
        count(*) filter (where days_ago < 30 and is_on_time)                    as on_time_30d,
        count(*) filter (where days_ago < 30 and had_exception)                 as exceptions_30d,
        count(*) filter (where is_overdue_open)                                 as overdue_open_now,
        mode(carrier_name) filter (where days_ago < 30)                         as main_carrier_30d
    from shipments
    group by merchant_id
),

scored as (
    select
        m.merchant_id,
        m.merchant_name,
        m.plan,
        m.country,
        coalesce(p.shipments_30d, 0)                                            as shipments_30d,
        coalesce(p.shipments_prev_30d, 0)                                       as shipments_prev_30d,
        coalesce(p.delivered_30d, 0)                                            as delivered_30d,
        round(100.0 * (p.shipments_30d - p.shipments_prev_30d)
              / nullif(p.shipments_prev_30d, 0), 1)                             as volume_change_pct,
        round(p.on_time_30d / nullif(p.delivered_30d, 0), 3)                    as on_time_rate_30d,
        coalesce(p.exceptions_30d, 0)                                           as exceptions_30d,
        coalesce(p.overdue_open_now, 0)                                         as overdue_open_now,
        p.main_carrier_30d
    from {{ ref('dim_merchants') }} as m
    left join per_merchant as p using (merchant_id)
)

select
    *,
    case
        when shipments_prev_30d >= {{ min_volume }} and shipments_30d = 0
            then 'churned'
        when shipments_prev_30d >= {{ min_volume }} and volume_change_pct <= -30
            then 'at_risk'
        when delivered_30d >= {{ min_delivered }} and on_time_rate_30d < 0.85
            then 'at_risk'
        when shipments_prev_30d >= {{ min_volume }} and volume_change_pct <= -15
            then 'watch'
        else 'healthy'
    end                                                                         as health_status,
    case
        when shipments_prev_30d >= {{ min_volume }} and shipments_30d = 0
            then 'No shipments in the last 30 days'
        when shipments_prev_30d >= {{ min_volume }} and volume_change_pct <= -30
            then 'Volume down ' || abs(volume_change_pct) || '% vs previous 30 days'
        when delivered_30d >= {{ min_delivered }} and on_time_rate_30d < 0.85
            then 'Only ' || round(on_time_rate_30d * 100)::int || '% on time, mostly ' || main_carrier_30d
        when shipments_prev_30d >= {{ min_volume }} and volume_change_pct <= -15
            then 'Volume down ' || abs(volume_change_pct) || '% vs previous 30 days'
    end                                                                         as health_reason
from scored
