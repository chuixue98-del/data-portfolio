select
    upper(trim(carrier_code)) as carrier_code,
    carrier_name
from {{ source('raw', 'carriers') }}
