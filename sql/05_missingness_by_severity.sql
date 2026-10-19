-- Data quality: is "unknown" independent of severity? (If not, dropping unknowns biases results.)
select
    case when speed_limit_code = 0 then 'speed limit unknown' else 'speed limit known' end as field_state,
    count(*) as crashes,
    round(100.0 * count(*) filter (where severity <= 2) / count(*), 1) as ksi_pct
from accidents group by 1
union all
select
    case when lighting in (6, 11) then 'lighting unknown' else 'lighting known' end,
    count(*),
    round(100.0 * count(*) filter (where severity <= 2) / count(*), 1)
from accidents group by 1
order by 1;
