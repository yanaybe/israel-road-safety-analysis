-- Q4. When do serious crashes happen, and when is a crash most likely to kill?
select weekday, hour,
       count(*)                              as crashes,
       count(*) filter (where severity <= 2) as killed_or_serious,
       count(*) filter (where severity = 1)  as fatal
from accidents
group by all
order by weekday, hour;
