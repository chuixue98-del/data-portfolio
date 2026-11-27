-- A parcel cannot be delivered before its label was created.
-- Returns the rows that break the rule; the test passes when there are none.
select shipment_id, created_at, delivered_at
from {{ ref('fct_shipments') }}
where delivered_at < created_at
