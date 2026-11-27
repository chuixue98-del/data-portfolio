-- Every merchant with shipments must appear in the health table,
-- otherwise Customer Success would miss them in the CRM.
select distinct f.merchant_id
from {{ ref('fct_shipments') }} as f
left join {{ ref('mart_merchant_health') }} as h using (merchant_id)
where h.merchant_id is null
