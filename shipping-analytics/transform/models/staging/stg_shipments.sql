with source as (
    select * from {{ source('raw', 'shipments') }}
),

cleaned as (
    select
        shipment_id,
        merchant_id,
        -- Source systems send ' dhl ', 'dhl' and 'DHL' for the same carrier
        upper(trim(carrier_code))                        as carrier_code,
        lower(service_level)                             as service_level,
        upper(destination_country)                       as destination_country,
        cast(weight_kg as double)                        as weight_kg_raw,
        cast(shipping_cost_eur as decimal(10, 2))        as shipping_cost_eur,
        cast(created_at as timestamp)                    as created_at,
        cast(promised_delivery_date as date)             as promised_delivery_date,
        _loaded_at
    from source
)

select
    shipment_id,
    merchant_id,
    carrier_code,
    service_level,
    destination_country,
    -- A weight of zero or less is a typo; keep the row, drop the value, flag it
    case when weight_kg_raw > 0 then weight_kg_raw end   as weight_kg,
    weight_kg_raw <= 0                                    as has_invalid_weight,
    shipping_cost_eur,
    created_at,
    promised_delivery_date,
    _loaded_at
from cleaned
-- The export repeats some rows: keep one per shipment
qualify row_number() over (partition by shipment_id order by _loaded_at) = 1
