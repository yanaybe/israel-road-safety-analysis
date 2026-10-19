-- Load the five CBS yearly files into one table with readable column names.
-- Codes are kept as numbers; labels come from the CBS dictionary via `codes`.
create or replace table accidents as
select
    pk_teuna_fikt                         as accident_id,      -- CBS fictitious id, not traceable
    SHNAT_TEUNA                           as year,
    HODESH_TEUNA                          as month,
    (SHAA - 1) // 4                       as hour,             -- SHAA = 15-minute slot 1..96
    YOM_BASHAVUA                          as weekday,          -- 1 = Sunday ... 7 = Saturday
    YOM_LAYLA = 5                         as is_night,
    SUG_YOM                               as day_type,         -- 1 holiday, 2 holiday eve, 3 intermediate, 4 other
    HUMRAT_TEUNA                          as severity,         -- 1 fatal, 2 serious, 3 light
    SUG_TEUNA                             as crash_type,
    SUG_DEREH                             as road_type,        -- 1/2 urban (junction / not), 3/4 interurban, 5 off-road
    SUG_DEREH in (1, 2)                   as is_urban,
    MEHIRUT_MUTERET                       as speed_limit_code, -- 0 unknown, 1 = up to 50 ... 8 = 120
    TEURA                                 as lighting,
    MEZEG_AVIR                            as weather,
    PNE_KVISH                             as surface,
    THUM_GEOGRAFI = 2                     as is_judea_samaria,
    MAHOZ                                 as district,
    EZOR_TIVI                             as natural_region,
    KVISH1                                as road_number,
    KM                                    as km_tenths,        -- road kilometre, in units of 100 m
    X                                     as itm_x,            -- Israeli Transverse Mercator (EPSG:2039)
    Y                                     as itm_y
from read_csv_auto('data/raw/accidents_*.csv', union_by_name = true);

create or replace table codes as
select cast(split_part(line, ',', 1) as integer) as code_table,
       cast(split_part(line, ',', 2) as integer) as code,
       trim(regexp_replace(line, '^[^,]*,[^,]*,', ''), '"') as label
from (select column0 as line from read_csv('data/raw/dictionary_2024.csv', header = true,
      columns = {'column0': 'VARCHAR'}, delim = '\x01'));
