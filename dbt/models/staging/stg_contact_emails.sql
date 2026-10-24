select source_row, lower(trim(email)) as email
from (
    unpivot {{ source('raw', 'contacts') }}
    on columns('^E-mail \d+ - Value$')
    into name email_slot value email
)
where nullif(trim(email), '') is not null
