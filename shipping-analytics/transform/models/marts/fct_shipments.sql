with shipments as (
    select * from {{ ref('stg_shipments') }}
),

milestones as (
    select * from {{ ref('int_shipment_milestones') }}
),

carriers as (
    select * from {{ ref('stg_carriers') }}
),

-- The last day with data. Used instead of today, so results do not change over time.
as_of as (
    select max(event_at)::date as as_of_date from {{ ref('fct_tracking_events') }}
)

select
    s.shipment_id,
    s.merchant_id,
    s.carrier_code,
    coalesce(c.carrier_name, 'Unknown')                          as carrier_name,
    s.service_level,
    s.destination_country,
    s.weight_kg,
    s.has_invalid_weight,
    s.shipping_cost_eur,
    s.created_at,
    s.created_at::date                                           as created_date,
    s.promised_delivery_date,
    m.picked_up_at,
    m.delivered_at,
    coalesce(m.current_status, 'label_created')                  as current_status,
    date_diff('day', s.created_at::date, m.delivered_at::date)   as transit_days,
    -- On time: delivered on or before the promised date. Empty while not delivered.
    case
        when m.delivered_at is not null then m.delivered_at::date <= s.promised_delivery_date
    end                                                          as is_on_time,
    -- Late and still open: the promised date has passed and the parcel is not delivered
    m.delivered_at is null
        and m.returned_at is null
        and s.promised_delivery_date < a.as_of_date              as is_overdue_open,
    m.exception_at is not null                                   as had_exception,
    m.returned_at is not null                                    as was_returned
from shipments as s
left join milestones as m using (shipment_id)
left join carriers as c using (carrier_code)
cross join as_of as a
