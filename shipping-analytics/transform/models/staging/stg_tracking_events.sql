with source as (
    select * from {{ source('raw', 'tracking_events') }}
)

select
    event_id,
    shipment_id,
    json_extract_string(event, '$.status')                          as status,
    cast(json_extract_string(event, '$.timestamp') as timestamp)    as event_at,
    json_extract_string(carrier, '$.code')                          as carrier_code,
    _source_file,
    _loaded_at
from source
-- The API sometimes sends the same event twice: keep the first one loaded
qualify row_number() over (partition by event_id order by _loaded_at) = 1
