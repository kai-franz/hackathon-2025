\echo =========================================================
\echo  Adjustable-scale e-commerce demo
\echo  Use:  psql -f ecommerce_schema_and_load.sql -v scale=10
\echo ---------------------------------------------------------

-- 0. Scaling factor -----------------------------------------------------------
\if :{?scale}
  \echo ==> Using scale factor :scale
\else
  \set scale 1
  \echo ==> No scale supplied; defaulting to 1
\endif

-- 1. Schema -------------------------------------------------------------------
\echo ==> Dropping / creating schema...
DROP SCHEMA IF EXISTS demo CASCADE;
CREATE SCHEMA demo;
SET search_path = demo, public;
\echo ...schema ready.

\echo ==> Creating tables...
-- Customers -------------------------------------------------------------------
CREATE TABLE customers (
  customer_id  BIGSERIAL PRIMARY KEY,
  username     TEXT NOT NULL UNIQUE,
  full_name    TEXT NOT NULL,
  email        TEXT NOT NULL UNIQUE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Addresses -------------------------------------------------------------------
CREATE TABLE addresses (
  address_id   BIGSERIAL PRIMARY KEY,
  customer_id  BIGINT NOT NULL REFERENCES customers ON DELETE CASCADE,
  line1        TEXT NOT NULL,
  city         TEXT NOT NULL,
  state        TEXT NOT NULL,
  postal_code  TEXT NOT NULL,
  country      TEXT NOT NULL DEFAULT 'US',
  is_default   BOOLEAN NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX ON addresses(customer_id) WHERE is_default;

-- Products & Categories -------------------------------------------------------
CREATE TABLE categories (
  category_id  BIGSERIAL PRIMARY KEY,
  name         TEXT NOT NULL UNIQUE
);

CREATE TABLE products (
  product_id   BIGSERIAL PRIMARY KEY,
  category_id  BIGINT NOT NULL REFERENCES categories,
  name         TEXT NOT NULL,
  price        NUMERIC(10,2) NOT NULL CHECK (price >= 0),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON products(category_id);

-- Suppliers & mapping ---------------------------------------------------------
CREATE TABLE suppliers (
  supplier_id  BIGSERIAL PRIMARY KEY,
  name         TEXT NOT NULL UNIQUE,
  contact_email TEXT
);

CREATE TABLE product_suppliers (
  product_id   BIGINT NOT NULL REFERENCES products ON DELETE CASCADE,
  supplier_id  BIGINT NOT NULL REFERENCES suppliers ON DELETE CASCADE,
  lead_days    INTEGER NOT NULL CHECK (lead_days BETWEEN 1 AND 60),
  PRIMARY KEY (product_id, supplier_id)
);

-- Inventory -------------------------------------------------------------------
CREATE TABLE inventory (
  product_id   BIGINT PRIMARY KEY REFERENCES products ON DELETE CASCADE,
  in_stock_qty INTEGER NOT NULL CHECK (in_stock_qty >= 0),
  last_updated TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Orders & Items --------------------------------------------------------------
CREATE TABLE orders (
  order_id         BIGSERIAL PRIMARY KEY,
  customer_id      BIGINT NOT NULL REFERENCES customers,
  ship_address_id  BIGINT NOT NULL REFERENCES addresses,
  order_ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
  status           TEXT NOT NULL CHECK (status IN ('PENDING','PAID','SHIPPED','CANCELLED'))
);
CREATE INDEX ON orders(customer_id);
CREATE INDEX ON orders(order_ts);

CREATE TABLE order_items (
  order_id    BIGINT NOT NULL REFERENCES orders ON DELETE CASCADE,
  line_no     INTEGER NOT NULL,
  product_id  BIGINT NOT NULL REFERENCES products,
  qty         INTEGER NOT NULL CHECK (qty > 0),
  unit_price  NUMERIC(10,2) NOT NULL CHECK (unit_price >= 0),
  PRIMARY KEY (order_id, line_no)
);
\echo ...tables created.

-- 2. Synthetic data generation ------------------------------------------------
\echo ==> Loading reference data

-- 2.1 Categories --------------------------------------------------------------
\echo  ...inserting 10 categories
INSERT INTO categories(name)
SELECT 'Category ' || g
FROM generate_series(1, 10) AS g;

-- 2.2 Suppliers ---------------------------------------------------------------
\echo  ...inserting about (200 * :scale) suppliers
INSERT INTO suppliers(name, contact_email)
SELECT
  'Supplier ' || g,
  'supplier' || g || '@example.com'
FROM generate_series(1, 200 * :scale) AS g;

-- 2.3 Products ----------------------------------------------------------------
\echo  ...inserting about (1000 * :scale) products
INSERT INTO products(category_id, name, price)
SELECT
  (random()*9 + 1)::int,
  'Product ' || g,
  round((random()*90 + 10)::numeric, 2)
FROM generate_series(1, 1000 * :scale) AS g;

-- 2.4 Product⇄supplier links --------------------------------------------------
\echo  ...mapping products to suppliers
INSERT INTO product_suppliers(product_id, supplier_id, lead_days)
SELECT
  p.product_id,
  (random() * (200 * :scale - 1) + 1)::bigint,
  (random() * 29 + 2)::int
FROM products AS p
JOIN LATERAL generate_series(1, (random() * 2 + 1)::int) AS t(x) ON true
ON CONFLICT DO NOTHING;

-- 2.5 Inventory ---------------------------------------------------------------
\echo  ...generating inventory snapshot
INSERT INTO inventory(product_id, in_stock_qty)
SELECT product_id, (random()*500)::int
FROM products;

-- 2.6 Customers ---------------------------------------------------------------
\echo  ...inserting about (1000 * :scale) customers
INSERT INTO customers(username, full_name, email)
SELECT
  'user' || g,
  initcap(md5(g::text)) || ' ' || initcap(md5((g+1)::text)),
  'user' || g || '@example.com'
FROM generate_series(1, 1000 * :scale) AS g;

-- 2.7 Addresses ---------------------------------------------------------------
\echo  ...creating addresses (~1.5 × customers)
INSERT INTO addresses(customer_id, line1, city, state, postal_code, is_default)
SELECT
  c.customer_id,
  'Street ' || (g*3),
  'City '   || (g%100),
  'ST',
  to_char(10000 + g, '00000'),
  (g % 2 = 0)
FROM customers AS c
JOIN LATERAL generate_series(1, CASE WHEN random() < 0.3 THEN 2 ELSE 1 END) AS g(x) ON true;

-- 2.8 Orders ------------------------------------------------------------------
\echo  ...creating orders (~10 × customers)
-- Batched insert into order_items (10 000 base orders per batch)
create temp table scale_factor as select :scale as scale;

DO $$
DECLARE
  batch_size   int := 10000;   -- number of *orders* per batch
  offset_val   int := 0;       -- running OFFSET
  inserted_rows int;           -- rows inserted in the most-recent batch
  scale_factor int := 10;
BEGIN
  LOOP
    /* Insert one batch and see how many rows we produced */
    WITH ins AS (
      INSERT INTO order_items
      SELECT
        o.order_id,
        gs.i,
        (random() * (1000 * scale_factor - 1) + 1)::bigint,
        (random() * 4 + 1)::int,
        round((random() * 90 + 10)::numeric, 2)
      FROM (
        /* Grab the next block of orders deterministically */
        SELECT order_id
        FROM orders
        ORDER BY order_id
        LIMIT batch_size
        OFFSET offset_val
      ) AS o
      CROSS JOIN LATERAL generate_series(1,
                     (random() * 4 + 1)::int) AS gs(i)
      RETURNING 1
    )
    SELECT COUNT(*) INTO inserted_rows FROM ins;

    /* Stop once no more orders remain */
    EXIT WHEN inserted_rows = 0;

    /* Advance to the next batch */
    offset_val := offset_val + batch_size;
  END LOOP;
END
$$;

-- 2.9 Order items -------------------------------------------------------------
\echo  ...inserting order items (staged for speed)
INSERT INTO order_items
SELECT
  o.order_id,
  gs.i,
  (random() * (1000 * :scale - 1) + 1)::bigint,
  (random() * 4 + 1)::int,
  round((random() * 90 + 10)::numeric, 2)
FROM orders AS o
CROSS JOIN LATERAL generate_series(1, (random() * 4 + 1)::int) AS gs(i);

\echo  ...order items inserted

\echo ==> Data generation complete.

-- 3. Final ANALYZE ------------------------------------------------------------
\echo ==> Running ANALYZE so statistics are up-to-date
ANALYZE;

\echo =========================================================
\echo  Done!  Database is ready.  Happy testing.
\echo =========================================================