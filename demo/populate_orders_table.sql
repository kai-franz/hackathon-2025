SET search_path = demo;

-- Insert a single order for each customer
DO $$
BEGIN
    FOR i IN 1..1000 LOOP
        INSERT INTO orders (customer_id,
                            ship_address_id,
                            order_ts,
                            status)
        SELECT
            c.customer_id,

            /* Shipping address: take the default if it exists, else the lowest id */
            ( SELECT ad.address_id
              FROM addresses   AS ad
              WHERE ad.customer_id = c.customer_id
              ORDER BY ad.is_default DESC, ad.address_id
              LIMIT 1 )                               AS ship_address_id,

            /* Order placed some time in the last 365 days */
            now() - (random() * interval '365 days')  AS order_ts,

            /* Weighted random status */
            ( CASE
                WHEN r < 0.05 THEN 'CANCELLED'  -- 5 %
                WHEN r < 0.15 THEN 'PENDING'    -- 10 %
                WHEN r < 0.45 THEN 'SHIPPED'    -- 30 %
                ELSE              'PAID'        -- 55 %
              END )                              AS status
        FROM (SELECT * FROM customers LIMIT 10 OFFSET i * 10) AS c
        CROSS JOIN LATERAL (SELECT random() AS r) AS t;
    END LOOP;
END
$$;
