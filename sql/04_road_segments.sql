-- Q3. Interurban road segments of 1 km (road number + km), with fatal-or-serious
-- crash counts in a "selection" period (2020-2022) and a "test" period (2023-2024).
-- km markers are in units of 100 m; negative markers are data errors and excluded.
select
    cast(road_number as integer)                       as road,
    cast(floor(km_tenths / 10) as integer)             as km,
    count(*)                                           as injury_crashes,
    count(*) filter (where severity <= 2 and year <= 2022) as ksi_2020_22,
    count(*) filter (where severity <= 2 and year >= 2023) as ksi_2023_24,
    count(*) filter (where severity = 3 and year <= 2022)  as light_2020_22,
    count(*) filter (where severity = 3)                   as light_all_years,
    count(*) filter (where severity = 1)               as fatal_all_years,
    avg(itm_x)                                         as itm_x,
    avg(itm_y)                                         as itm_y,
    mode(natural_region)                               as natural_region,
    mode(district)                                     as district
from accidents
where road_type in (3, 4) and road_number is not null and km_tenths >= 0
group by 1, 2
order by road, km;
