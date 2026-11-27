select
    merchant_id,
    trim(merchant_name)          as merchant_name,
    upper(trim(country))         as country,
    lower(trim(plan))            as plan,
    cast(signup_date as date)    as signup_date,
    _loaded_at
from {{ source('raw', 'merchants') }}
