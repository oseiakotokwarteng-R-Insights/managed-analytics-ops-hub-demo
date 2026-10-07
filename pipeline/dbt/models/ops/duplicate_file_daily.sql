-- A different file name carrying exactly the same bytes as an earlier file: the carrier re-sent a file.
select f.stream, f.rel_path, f.arrival, f.loaded_as_of as as_of, f.rows_loaded,
       first_value(f.rel_path) over (partition by f.sha256 order by f.arrival, f.rel_path) as duplicate_of
from {{ ref('ops_file_arrival') }} f
where f.rows_loaded > 0
qualify row_number() over (partition by f.sha256 order by f.arrival, f.rel_path) > 1
