import pytest
from sqlalchemy import select

from app.models import ProductPlatform
from helpers import signup


def names(response):
    return [p["name"] for p in response.json()["data"]]


# ------------------------------------------------------------------- product list & filters
async def test_list_products_envelope_and_pagination(client, world):
    r = await client.get("/api/products?page_size=2&page=1")
    body = r.json()
    assert r.status_code == 200 and body["success"] is True and len(body["data"]) == 2
    assert body["meta"] == {"page": 1, "page_size": 2, "total": 4, "pages": 2}
    page2 = await client.get("/api/products?page_size=2&page=2")
    assert not set(names(r)) & set(names(page2))


async def test_product_card_contents(client, world):
    card = next(p for p in (await client.get("/api/products?category=tv")).json()["data"])
    assert card["name"].startswith("Samsung") and card["category"] == "tv"
    assert card["current_price"] == 23000 and card["best_platform"] == "flipkart"
    assert {p["platform"] for p in card["platforms"]} == {"amazon", "flipkart"}
    assert card["deal_score"] >= 85 and card["deal_label"] in ("great", "exceptional")
    assert card["historical_low"] == 23000 and card["typical_price"] > 23000
    assert card["rating"] == 4.5 and card["review_count"] == 6100
    assert card["is_stale"] is False and card["price_updated_at"]


async def test_filters(client, world):
    assert names(await client.get("/api/products?category=laptops&sort=name")) == ["HP Laptop 15 i5", "Lenovo IdeaPad Slim 3"]
    assert names(await client.get("/api/products?brand=lenovo")) == ["Lenovo IdeaPad Slim 3"]
    assert names(await client.get("/api/products?min_price=30000&max_price=40000")) == ["Lenovo IdeaPad Slim 3"]
    assert names(await client.get("/api/products?platform=flipkart&sort=price_asc")) == ["Samsung 55 inch 4K Smart TV", "Lenovo IdeaPad Slim 3"]
    assert names(await client.get("/api/products?deal_score=85")) == ["Samsung 55 inch 4K Smart TV"]


async def test_sorting(client, world):
    asc = names(await client.get("/api/products?sort=price_asc"))
    desc = names(await client.get("/api/products?sort=price_desc"))
    assert asc[0] == "Acme Brand New Gadget" and desc[0] == "HP Laptop 15 i5"
    by_deal = (await client.get("/api/products?sort=deal_score")).json()["data"]
    scores = [p["deal_score"] for p in by_deal if p["deal_score"] is not None]
    assert scores == sorted(scores, reverse=True)
    assert by_deal[-1]["deal_score"] is None  # unscored products sort last


@pytest.mark.parametrize("query,message", [
    ("sort=bogus", "Unknown sort"), ("min_price=100&max_price=10", "min_price"),
    ("page=0", "Validation failed"), ("page_size=500", "Validation failed"), ("deal_score=150", "Validation failed"),
])
async def test_invalid_query_params(client, world, query, message):
    r = await client.get(f"/api/products?{query}")
    assert r.status_code == 422 and message in r.json()["message"]


async def test_new_product_says_not_enough_history_instead_of_a_score(client, world):
    card = next(p for p in (await client.get("/api/products")).json()["data"] if p["name"].startswith("Acme"))
    assert card["deal_score"] is None and card["deal_label"] == "insufficient_data"
    assert card["note"] == "Not enough historical data yet"
    assert card["current_price"] == 999  # the live price is still shown


# ------------------------------------------------------------------- detail, prices, offers
async def test_product_detail_explains_the_deal(client, world):
    d = (await client.get(f"/api/products/{world['tv']}")).json()["data"]
    codes = {e["code"] for e in d["explanation"]}
    assert {"below_avg_30d", "at_low", "cheapest_platform", "multi_platform"} <= codes
    assert d["specifications"] == {"size": "55 inch"} and d["model_number"] == "UA55"
    assert d["offers"][0]["offer_type"] == "bank" and d["offers"][0]["platform"] == "flipkart"
    assert d["score_breakdown"]["deal"]["factors"]


async def test_unknown_product_is_404(client, world):
    for path in ("", "/prices", "/offers", "/compare", "/buy"):
        r = await client.get(f"/api/products/999999{path}")
        assert r.status_code == 404 and r.json()["success"] is False


async def test_price_history_series_and_message(client, world):
    r = await client.get(f"/api/products/{world['tv']}/prices?days=90")
    h = r.json()["data"]
    assert h["resolution"] == "daily" and set(h["series"]) == {"amazon", "flipkart"}
    assert h["has_sufficient_history"] is True and r.json()["message"] is None
    last = h["series"]["flipkart"][-1]
    assert last["price"] == 23000 and last["low"] <= last["price"] <= last["high"]

    raw = (await client.get(f"/api/products/{world['tv']}/prices?days=7&platform=amazon")).json()["data"]
    assert raw["resolution"] == "raw" and list(raw["series"]) == ["amazon"]

    new = await client.get(f"/api/products/{world['new']}/prices")
    assert new.json()["message"] == "Not enough historical data yet"
    assert new.json()["data"]["has_sufficient_history"] is False and new.json()["data"]["series"]["amazon"]


async def test_offers_endpoint(client, world):
    offers = (await client.get(f"/api/products/{world['tv']}/offers")).json()["data"]
    assert [o["description"] for o in offers] == ["5% off with card X"]


# ------------------------------------------------------------------- compare & buy
async def test_compare_amazon_vs_flipkart(client, world):
    c = (await client.get(f"/api/products/{world['tv']}/compare")).json()["data"]
    assert c["best_platform"] == "flipkart" and c["price_difference"] == 3000
    flip, amazon = c["platforms"]
    assert (flip["platform"], flip["price"], flip["difference_vs_cheapest"]) == ("flipkart", 23000, 0)
    assert (amazon["platform"], amazon["difference_vs_cheapest"]) == ("amazon", 3000)
    assert flip["bank_offers"][0]["discount_amount"] == 1150 and flip["price_after_offers"] == 21850
    assert flip["field_status"]["shipping"] == "unavailable" and flip["field_status"]["price_after_offers"] == "estimated"
    assert flip["shipping"] is None and flip["warranty"] is None  # never invented
    assert "Flipkart is cheapest at ₹23,000" in c["summary"] and "₹3,000 less than Amazon" in c["summary"]


async def test_compare_single_platform(client, world):
    c = (await client.get(f"/api/products/{world['laptop_flat']}/compare")).json()["data"]
    assert c["best_platform"] == "amazon" and c["price_difference"] is None and c["summary"].startswith("Only available on Amazon")


async def test_buy_links_use_affiliate_only_when_real(client, world):
    flip = (await client.get(f"/api/products/{world['tv']}/buy")).json()["data"]
    assert flip["platform"] == "flipkart" and flip["is_affiliate_link"] is True and "tag=real" in flip["url"]
    amazon = (await client.get(f"/api/products/{world['tv']}/buy?platform=amazon")).json()["data"]
    assert amazon["is_affiliate_link"] is False and amazon["url"] == "https://amazon.invalid/AZ-TV"
    assert "no affiliate tracking" in amazon["note"]
    assert (await client.get(f"/api/products/{world['tv']}/buy?platform=croma")).status_code == 404


async def test_stale_prices_are_flagged(client, world, factory):
    from datetime import timedelta

    async with factory() as s:
        for l in await s.scalars(select(ProductPlatform).where(ProductPlatform.platform == "amazon")):
            l.price_captured_at = l.price_captured_at - timedelta(hours=10)
        await s.commit()
    cards = {p["name"]: p for p in (await client.get("/api/products")).json()["data"]}
    assert cards["HP Laptop 15 i5"]["is_stale"] is True
    assert cards["Samsung 55 inch 4K Smart TV"]["is_stale"] is False  # best price is on fresh Flipkart data
    amazon_row = next(p for p in cards["Samsung 55 inch 4K Smart TV"]["platforms"] if p["platform"] == "amazon")
    assert amazon_row["is_stale"] is True


@pytest.mark.parametrize("word", ["laptop", "Laptops", "LAPTOP", "notebook", "laptops"])
async def test_category_filter_understands_everyday_words(client, world, word):
    assert len((await client.get("/api/products", params={"category": word})).json()["data"]) == 2


@pytest.mark.parametrize("word,expected", [("television", 1), ("tvs", 1), ("phone", 0), ("nonsense", 0)])
async def test_category_aliases_and_unknown(client, world, word, expected):
    assert len((await client.get("/api/products", params={"category": word})).json()["data"]) == expected


async def test_compare_many_picks_winners_and_explains(client, world):
    ids = f"{world['tv']},{world['laptop_flat']},{world['laptop_drop']}"
    r = await client.get(f"/api/compare?ids={ids}")
    c = r.json()["data"]
    assert r.status_code == 200 and [p["id"] for p in c["products"]] == [world["tv"], world["laptop_flat"], world["laptop_drop"]]
    assert c["cheapest_id"] == world["tv"] and c["best_deal_id"] == world["tv"]
    assert "ram" in c["spec_keys"] and any("lowest price" in line for line in c["summary"])


@pytest.mark.parametrize("ids", ["1", "1,1", "1,2,3,4,5,6", "a,b", ""])
async def test_compare_many_validates_ids(client, world, ids):
    assert (await client.get("/api/compare", params={"ids": ids})).status_code == 422


async def test_compare_many_unknown_product_is_404(client, world):
    assert (await client.get(f"/api/compare?ids={world['tv']},999999")).status_code == 404


async def test_detail_reports_when_historical_low_was_seen(client, world):
    stats = (await client.get(f"/api/products/{world['tv']}")).json()["data"]["stats"]
    assert stats["historical_low"] == "23000.00" and stats["historical_low_at"]


async def test_meta_reports_demo_mode_with_mock_providers(client):
    data = (await client.get("/api/meta")).json()["data"]
    assert data["data_mode"] == "demo" and {p["name"] for p in data["providers"]} == {"amazon", "flipkart"}


# ------------------------------------------------------------------- search & categories
async def test_search(client, world):
    assert names(await client.get("/api/search?q=samsung")) == ["Samsung 55 inch 4K Smart TV"]
    assert names(await client.get("/api/search?q=laptop%20i5")) == ["HP Laptop 15 i5"]
    assert names(await client.get("/api/search?q=UA55")) == ["Samsung 55 inch 4K Smart TV"]  # model number
    assert names(await client.get('/api/search?q=55"')) == ["Samsung 55 inch 4K Smart TV"]  # unit normalisation
    assert (await client.get("/api/search?q=nothingmatches")).json()["data"] == []


async def test_search_requires_query_and_is_injection_safe(client, world):
    assert (await client.get("/api/search")).status_code == 422
    assert (await client.get("/api/search?q=%20")).status_code == 422
    for evil in ("%25", "_", "'; DROP TABLE products; --", "\\"):
        r = await client.get("/api/search", params={"q": evil})
        assert r.status_code == 200
    assert len((await client.get("/api/products")).json()["data"]) == 4  # nothing was dropped


async def test_categories(client, world):
    cats = {c["slug"]: c["product_count"] for c in (await client.get("/api/categories")).json()["data"]}
    assert cats == {"laptops": 2, "tv": 1}


# ------------------------------------------------------------------- deals
async def test_deals_listing_only_scored_sorted(client, world):
    deals = (await client.get("/api/deals")).json()["data"]
    assert deals and all(d["deal_score"] is not None for d in deals)
    assert deals[0]["name"].startswith("Samsung")
    assert all(d["name"] != "Acme Brand New Gadget" for d in deals)


async def test_best_deals_threshold_and_caching(client, world):
    best = (await client.get("/api/deals/best")).json()["data"]
    # The TV and the laptop with a real 20% drop qualify; the flat-price laptop and the
    # product with no history do not.
    assert [d["name"] for d in best] == ["Samsung 55 inch 4K Smart TV", "Lenovo IdeaPad Slim 3"]
    assert all(d["deal_score"] >= 70 for d in best)
    strict = (await client.get("/api/deals/best?deal_score=85")).json()["data"]
    assert [d["name"] for d in strict] == ["Samsung 55 inch 4K Smart TV"]
    assert (await client.get("/api/deals/best?limit=0")).status_code == 422


async def test_price_drops_and_historical_lows(client, world):
    drops = (await client.get("/api/deals/price-drops?hours=24")).json()["data"]
    assert [d["product"]["name"] for d in drops] == ["Lenovo IdeaPad Slim 3"]
    assert drops[0]["event"]["previous_price"] == 40000 and drops[0]["event"]["detail"]["drop_pct"] == 20.0
    lows = (await client.get("/api/deals/historical-lows")).json()["data"]
    assert [d["product"]["name"] for d in lows] == ["Samsung 55 inch 4K Smart TV"]
    assert (await client.get("/api/deals/price-drops?hours=1")).json()["data"] == []  # event is 2h old
    assert (await client.get("/api/deals/price-drops?category=tv")).json()["data"] == []  # filters apply


# ------------------------------------------------------------------- alerts
async def test_alert_lifecycle(client, world):
    _, headers = await signup(client)
    assert (await client.post("/api/alerts", json={"product_id": world["tv"], "target_price": 20000})).status_code == 401

    r = await client.post("/api/alerts", headers=headers, json={"product_id": world["tv"], "target_price": 20000})
    a = r.json()["data"]
    assert r.status_code == 201 and a["current_price"] == 23000 and a["amount_above_target"] == 3000
    assert a["product_name"].startswith("Samsung") and a["is_active"] is True

    listed = (await client.get("/api/alerts", headers=headers)).json()["data"]
    assert [x["id"] for x in listed] == [a["id"]]
    assert (await client.delete(f"/api/alerts/{a['id']}", headers=headers)).status_code == 200
    assert (await client.get("/api/alerts", headers=headers)).json()["data"] == []


async def test_alert_validation(client, world):
    _, headers = await signup(client)
    post = lambda body: client.post("/api/alerts", headers=headers, json=body)  # noqa: E731
    assert (await post({"product_id": world["tv"], "target_price": 0})).status_code == 422
    assert (await post({"product_id": world["tv"], "target_price": -5})).status_code == 422
    assert (await post({"product_id": 999999, "target_price": 100})).status_code == 404
    bad_platform = await post({"product_id": world["laptop_flat"], "target_price": 100, "platform": "flipkart"})
    assert bad_platform.status_code == 422 and "not listed" in bad_platform.json()["message"]
    ok = await post({"product_id": world["tv"], "target_price": 100, "platform": "Amazon"})
    assert ok.status_code == 201 and ok.json()["data"]["platform"] == "amazon"


async def test_users_cannot_touch_each_others_alerts(client, world):
    _, alice = await signup(client, "alice@example.com")
    _, bob = await signup(client, "bob@example.com")
    alert_id = (await client.post("/api/alerts", headers=alice, json={"product_id": world["tv"], "target_price": 100})).json()["data"]["id"]
    assert (await client.delete(f"/api/alerts/{alert_id}", headers=bob)).status_code == 404
    assert (await client.get("/api/alerts", headers=bob)).json()["data"] == []
    assert len((await client.get("/api/alerts", headers=alice)).json()["data"]) == 1


# ------------------------------------------------------------------- profile & favourites
async def test_profile_and_notification_preferences(client, world):
    _, headers = await signup(client)
    ok = await client.patch("/api/me", headers=headers, json={"name": "New Name", "notification_preferences": {"email": True, "telegram": {"chat_id": 123}}})
    assert ok.status_code == 200 and ok.json()["data"]["name"] == "New Name"
    assert ok.json()["data"]["notification_preferences"] == {"email": True, "telegram": {"chat_id": "123"}}
    assert (await client.patch("/api/me", headers=headers, json={"notification_preferences": {"fax": True}})).status_code == 422
    assert (await client.patch("/api/me", headers=headers, json={"notification_preferences": {"email": "yes"}})).status_code == 422
    assert (await client.patch("/api/me", headers=headers, json={"name": "   "})).status_code == 422


async def test_favourite_products_and_categories(client, world):
    _, headers = await signup(client)
    assert (await client.put(f"/api/me/favorites/products/{world['tv']}", headers=headers)).status_code == 200
    assert (await client.put(f"/api/me/favorites/products/{world['tv']}", headers=headers)).status_code == 200  # idempotent
    assert (await client.put("/api/me/favorites/products/999999", headers=headers)).status_code == 404
    favs = (await client.get("/api/me/favorites/products", headers=headers)).json()["data"]
    assert [p["id"] for p in favs] == [world["tv"]]
    await client.delete(f"/api/me/favorites/products/{world['tv']}", headers=headers)
    assert (await client.get("/api/me/favorites/products", headers=headers)).json()["data"] == []

    assert (await client.put("/api/me/favorites/categories/laptops", headers=headers)).status_code == 200
    assert (await client.put("/api/me/favorites/categories/nope", headers=headers)).status_code == 404
    cats = (await client.get("/api/me/favorites/categories", headers=headers)).json()["data"]
    assert [c["slug"] for c in cats] == ["laptops"]


# ------------------------------------------------------------------- recommendations
async def test_recommendations_respect_constraints_and_explain(client, world):
    r = await client.post("/api/recommendations", json={"category": "laptops", "max_price": 60000, "priority": "value"})
    recs = r.json()["data"]
    assert r.status_code == 200 and [x["rank"] for x in recs] == list(range(1, len(recs) + 1))
    assert all(x["product"]["category"] == "laptops" and x["product"]["current_price"] <= 60000 for x in recs)
    assert recs[0]["reasons"] and any("Value score" in t for t in recs[0]["reasons"])
    assert (await client.post("/api/recommendations", json={"max_price": 100})).json()["data"] == []
    assert (await client.post("/api/recommendations", json={"limit": 99})).status_code == 422


async def test_price_priority_returns_cheapest_first(client, world):
    recs = (await client.post("/api/recommendations", json={"priority": "price", "limit": 3})).json()["data"]
    prices = [x["product"]["current_price"] for x in recs]
    assert prices == sorted(prices)


async def test_recommendations_use_favourite_categories(client, world):
    _, headers = await signup(client)
    await client.put("/api/me/favorites/categories/tv", headers=headers)
    recs = (await client.get("/api/recommendations", headers=headers)).json()["data"]
    assert recs and {x["product"]["category"] for x in recs} == {"tv"}
    anon = (await client.get("/api/recommendations")).json()["data"]
    assert {x["product"]["category"] for x in anon} >= {"tv"}
