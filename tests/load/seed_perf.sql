-- Synthetic data at realistic scale for performance testing. Run ONLY against a scratch database
-- (never the real one):  psql -U dealhunter -d dealhunter_perf -f seed_perf.sql
-- 5,000 products x 2 listings = 10,000 listings, each with 200 price observations = 2,000,000 price rows.
BEGIN;

INSERT INTO categories (name, slug) VALUES
  ('Mobiles','mobiles'), ('Laptops','laptops'), ('TV','tv'), ('Electronics','electronics'), ('Home Appliances','home-appliances');

INSERT INTO products (brand, name, normalized_name, model_number, variant_key, category_id, specifications, is_active)
SELECT 'Brand' || (i % 60),
       'Brand' || (i % 60) || ' ' || (ARRAY['Phone','Laptop','Smart TV','Headphones','Washing Machine'])[1 + (i % 5)] || ' ' || i,
       lower('brand' || (i % 60) || ' ' || (ARRAY['phone','laptop','smart tv','headphones','washing machine'])[1 + (i % 5)] || ' ' || i),
       'MODEL-' || i, '', 1 + (i % 5),
       jsonb_build_object('ram', (ARRAY['4GB','8GB','16GB','32GB'])[1 + (i % 4)], 'storage', (ARRAY['128GB','256GB','512GB','1TB'])[1 + (i % 4)]),
       true
FROM generate_series(1, 5000) i;

INSERT INTO product_platforms (product_id, platform, external_product_id, url, availability, current_price, current_mrp,
                               price_captured_at, rating, review_count, last_seen_at, seller_name, is_active)
SELECT p.id, pl.platform, pl.platform || '-' || p.id, 'https://' || pl.platform || '.invalid/' || p.id, 'in_stock',
       round((1000 + (p.id * 37) % 90000) * (CASE WHEN pl.platform = 'amazon' THEN 1.0 ELSE 0.97 END)::numeric, 2),
       round((1000 + (p.id * 37) % 90000) * 1.3::numeric, 2),
       now() - interval '10 minutes', 3.4 + random() * 1.6, (random() * 9000)::int, now(), 'Seller ' || (p.id % 20), true
FROM products p CROSS JOIN (VALUES ('amazon'), ('flipkart')) AS pl(platform);

-- 200 observations per listing, every 12 hours back ~100 days, noisy around the current price, with occasional dips.
INSERT INTO product_prices (product_platform_id, price, mrp, availability, captured_at)
SELECT l.id,
       round((l.current_price * (0.95 + random() * 0.12) * (CASE WHEN random() < 0.05 THEN 0.85 ELSE 1 END))::numeric, 2),
       l.current_mrp, 'in_stock', now() - (g * interval '12 hours')
FROM product_platforms l CROSS JOIN generate_series(1, 200) AS g;

COMMIT;
ANALYZE;
SELECT 'products' AS t, count(*) FROM products UNION ALL SELECT 'listings', count(*) FROM product_platforms UNION ALL SELECT 'price rows', count(*) FROM product_prices;
