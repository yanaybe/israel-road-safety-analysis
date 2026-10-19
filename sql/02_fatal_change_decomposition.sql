-- Q1b. Where did the rise in fatal crashes come from? 2020 vs 2024 by road type
-- and crash type, with each group's share of the total change.
with f as (
    select
        case when is_urban then 'Urban' when road_type in (3, 4) then 'Interurban' else 'Other' end as road,
        case crash_type
            when 1 then 'Pedestrian hit'
            when 5 then 'Head-on'
            when 2 then 'Front-to-side'
            when 3 then 'Rear-end'
            when 9 then 'Off-road / rollover' when 10 then 'Off-road / rollover'
            when 8 then 'Hit fixed object'
            else 'Other' end as kind,
        year
    from accidents where severity = 1 and year in (2020, 2024)
)
select road, kind,
       count(*) filter (where year = 2020) as fatal_2020,
       count(*) filter (where year = 2024) as fatal_2024,
       count(*) filter (where year = 2024) - count(*) filter (where year = 2020) as change
from f
group by all
order by change desc, road, kind;
