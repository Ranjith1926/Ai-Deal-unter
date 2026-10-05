"""Synthetic catalogue for development and tests. NOT real marketplace data.

Identifiers are fake (``MOCK-`` prefix, synthetic GTINs). The set deliberately includes the
edge cases the platform must handle: same product with different titles per platform,
variants that must stay separate, a platform-exclusive product, a missing MRP and an
out-of-stock listing.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MockListing:
    external_id: str
    title: str
    base_price: int
    mrp: int | None
    seller: str
    availability: str = "in_stock"
    asin: str | None = None
    rating: str | None = None
    review_count: int | None = None


@dataclass(frozen=True)
class MockItem:
    key: str
    brand: str
    category: str
    model_number: str
    gtin: str  # synthetic
    variant: dict[str, str] = field(default_factory=dict)
    specs: dict[str, str] = field(default_factory=dict)
    amazon: MockListing | None = None
    flipkart: MockListing | None = None


CATALOG: tuple[MockItem, ...] = (
    MockItem(
        "iphone16-128", "Apple", "mobiles", "MOCK-IP16-128", "9900000000011",
        {"storage": "128GB", "colour": "Black"}, {"display": "6.1 inch OLED", "ram": "8GB"},
        amazon=MockListing("MOCKB0A001", "Apple iPhone 16 (128 GB) - Black", 79900, 79900, "Appario Retail", asin="MOCKB0A001", rating="4.6", review_count=4120),
        flipkart=MockListing("MOCKMOBIP16128", "Apple iPhone 16 (Black, 128 GB)", 78900, 79900, "RetailNet", rating="4.7", review_count=8850),
    ),
    MockItem(
        "iphone16-256", "Apple", "mobiles", "MOCK-IP16-256", "9900000000028",
        {"storage": "256GB", "colour": "Black"}, {"display": "6.1 inch OLED", "ram": "8GB"},
        amazon=MockListing("MOCKB0A002", "Apple iPhone 16 (256 GB) - Black", 89900, 89900, "Appario Retail", asin="MOCKB0A002", rating="4.6", review_count=2210),
        flipkart=MockListing("MOCKMOBIP16256", "Apple iPhone 16 (Black, 256 GB)", 89900, 89900, "RetailNet", rating="4.7", review_count=3010),
    ),
    MockItem(
        "galaxy-s24", "Samsung", "mobiles", "MOCK-SM-S921", "9900000000035",
        {"storage": "256GB", "colour": "Onyx Black"}, {"display": "6.2 inch AMOLED", "ram": "8GB", "processor": "Exynos 2400"},
        amazon=MockListing("MOCKB0A003", "Samsung Galaxy S24 5G (Onyx Black, 8GB, 256GB)", 62999, 89999, "Cocoblu Retail", asin="MOCKB0A003", rating="4.4", review_count=3300),
        flipkart=MockListing("MOCKMOBGS24256", "SAMSUNG Galaxy S24 5G (Onyx Black, 256 GB) (8 GB RAM)", 61499, 89999, "SuperComNet", rating="4.5", review_count=5120),
    ),
    MockItem(
        "nord-ce4", "OnePlus", "mobiles", "MOCK-CPH2613", "9900000000042",
        {"storage": "128GB", "colour": "Dark Chrome"}, {"display": "6.7 inch AMOLED", "ram": "8GB"},
        amazon=MockListing("MOCKB0A004", "OnePlus Nord CE4 5G (Dark Chrome, 8GB RAM, 128GB)", 24999, 26999, "OnePlus Store", asin="MOCKB0A004", rating="4.2", review_count=9100),
        flipkart=MockListing("MOCKMOBNCE4128", "OnePlus Nord CE4 (Dark Chrome, 128 GB) (8 GB RAM)", 24999, 26999, "OnePlus Store", rating="4.3", review_count=12400),
    ),
    MockItem(
        "samsung-tv-55", "Samsung", "tv", "MOCK-UA55DUE77", "9900000000059",
        {"size": "55 inch"}, {"resolution": "4K UHD", "smart": "Yes"},
        amazon=MockListing("MOCKB0A005", "Samsung 138 cm (55 inches) Crystal 4K Vivid Pro Smart LED TV UA55DUE77", 52999, 79900, "Darshita Aashiyana", asin="MOCKB0A005", rating="4.3", review_count=7600),
        flipkart=MockListing("MOCKTVSAM55", "SAMSUNG Crystal 4K Vivid Pro 138 cm (55 inch) Ultra HD (4K) LED Smart Tizen TV", 49499, 79900, "RetailNet", rating="4.4", review_count=6100),
    ),
    MockItem(
        "lg-tv-43", "LG", "tv", "MOCK-43UR7500", "9900000000066",
        {"size": "43 inch"}, {"resolution": "4K UHD", "smart": "Yes"},
        amazon=MockListing("MOCKB0A006", "LG 108 cm (43 inches) 4K Ultra HD Smart LED TV 43UR7500", 31990, 52990, "Appario Retail", asin="MOCKB0A006", rating="4.2", review_count=2900),
        flipkart=MockListing("MOCKTVLG43", "LG UR7500 108 cm (43 inch) Ultra HD (4K) LED Smart WebOS TV", 32490, 52990, "SuperComNet", rating="4.3", review_count=3800),
    ),
    MockItem(
        "hp-15", "HP", "laptops", "MOCK-15FD0000", "9900000000073",
        {"ram": "16GB", "storage": "512GB"}, {"processor": "Intel Core i5", "display": "15.6 inch FHD"},
        amazon=MockListing("MOCKB0A007", "HP Laptop 15, 13th Gen Intel Core i5, 16GB, 512GB SSD", 54990, 69999, "Appario Retail", asin="MOCKB0A007", rating="4.1", review_count=1800),
        flipkart=MockListing("MOCKCOMHP15", "HP 15 Intel Core i5 13th Gen (16 GB/512 GB SSD/Windows 11) Laptop", 55990, 69999, "RetailNet", rating="4.2", review_count=2100),
    ),
    MockItem(
        "ideapad-slim3", "Lenovo", "laptops", "MOCK-82XQ00", "9900000000080",
        {"ram": "16GB", "storage": "512GB"}, {"processor": "AMD Ryzen 5", "display": "15.6 inch FHD"},
        amazon=MockListing("MOCKB0A008", "Lenovo IdeaPad Slim 3 AMD Ryzen 5 16GB 512GB", 42990, 63390, "Cloudtail", asin="MOCKB0A008", rating="4.0", review_count=1500),
        flipkart=MockListing("MOCKCOMLEN3", "Lenovo IdeaPad Slim 3 Ryzen 5 Hexa Core (16 GB/512 GB SSD)", 41990, 63390, "RetailNet", rating="4.1", review_count=2300),
    ),
    MockItem(
        "dell-inspiron", "Dell", "laptops", "MOCK-INS3520", "9900000000097",
        {"ram": "8GB", "storage": "512GB"}, {"processor": "Intel Core i3", "display": "15.6 inch FHD"},
        # MRP missing on Amazon; out of stock on Flipkart.
        amazon=MockListing("MOCKB0A009", "Dell Inspiron 3520 Intel Core i3 8GB 512GB", 36990, None, "Cloudtail", asin="MOCKB0A009", rating="3.9", review_count=640),
        flipkart=MockListing("MOCKCOMDEL3520", "DELL Inspiron Core i3 12th Gen (8 GB/512 GB SSD)", 35990, 49000, "RetailNet", availability="out_of_stock", rating="4.0", review_count=720),
    ),
    MockItem(
        "sony-xm5", "Sony", "electronics", "MOCK-WH1000XM5", "9900000000103",
        {"colour": "Black"}, {"type": "Over-ear", "noise_cancelling": "Yes"},
        amazon=MockListing("MOCKB0A010", "Sony WH-1000XM5 Wireless Noise Cancelling Headphones", 26990, 34990, "Appario Retail", asin="MOCKB0A010", rating="4.5", review_count=5400),
        flipkart=MockListing("MOCKACCSXM5", "SONY WH-1000XM5 Bluetooth Headset (Black, Over the Ear)", 27490, 34990, "SuperComNet", rating="4.5", review_count=4700),
    ),
    # Platform-exclusive products.
    MockItem(
        "boat-airdopes", "boAt", "electronics", "MOCK-AD141", "9900000000110",
        {"colour": "Black"}, {"type": "TWS earbuds"},
        flipkart=MockListing("MOCKACCBOAT141", "boAt Airdopes 141 Bluetooth Headset (Active Black, True Wireless)", 1099, 2990, "Imagine Marketing", rating="4.1", review_count=310000),
    ),
    MockItem(
        "lg-washer-7", "LG", "home-appliances", "MOCK-FHM1207", "9900000000127",
        {"capacity": "7 kg"}, {"type": "Front load"},
        amazon=MockListing("MOCKB0A012", "LG 7 Kg 5 Star Inverter Front Load Washing Machine FHM1207ZDL", 28990, 41990, "Appario Retail", asin="MOCKB0A012", rating="4.3", review_count=2600),
    ),
)
