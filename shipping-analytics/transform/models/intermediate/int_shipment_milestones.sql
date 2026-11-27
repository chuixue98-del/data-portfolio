-- One row per shipment: when it reached each step, and where it is now.
select
    shipment_id,
    min(case when status = 'in_transit' then event_at end)        as picked_up_at,
    min(case when status = 'delivered' then event_at end)         as delivered_at,
    min(case when status = 'returned' then event_at end)          as returned_at,
    min(case when status = 'exception' then event_at end)         as exception_at,
    arg_max(status, event_at)                                     as current_status,
    max(event_at)                                                 as last_event_at,
    count(*)                                                      as event_count
from {{ ref('fct_tracking_events') }}
group by shipment_id
