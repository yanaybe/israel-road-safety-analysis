-- Q1. Are roads getting safer? Crashes per year by severity, with and without
-- Judea & Samaria (published national figures use different scopes).
select
    year,
    count(*)                                                     as injury_crashes,
    count(*) filter (where severity = 1)                         as fatal,
    count(*) filter (where severity = 2)                         as serious,
    count(*) filter (where severity = 3)                         as light,
    count(*) filter (where severity = 1 and not is_judea_samaria) as fatal_excl_js,
    round(100.0 * count(*) filter (where severity <= 2) / count(*), 1) as ksi_share_pct
from accidents
group by year
order by year;
