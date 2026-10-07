-- (order_no, line_no) identifies exactly one current line.
select order_no, line_no, count(*) as n from {{ ref('fct_order_line') }} group by 1, 2 having count(*) > 1
