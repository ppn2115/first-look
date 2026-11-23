"""Settings for a First Look run. Change these for a new data room, not the code."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Config:
    # Stock codes that are not products (postage, fees, manual lines, vouchers, tests)
    non_product_codes: tuple = (
        "POST", "DOT", "M", "m", "C2", "D", "S", "B", "BANK CHARGES", "ADJUST",
        "ADJUST2", "AMAZONFEE", "PADS", "CRUK", "TEST001", "TEST002",
    )
    # Anything not starting with 5 digits is treated as non-product (gift_0001_*, DCGS*, ...)
    product_code_regex: str = r"^\d{5}"

    # Segmentation: a customer whose median order value is at or above this is "Large account"
    large_account_median_order_gbp: float = 500.0

    # Comparison periods (inclusive month ranges). Dec 2011 has only 9 days, so it is excluded.
    period_0: tuple = ("2009-12", "2010-11")
    period_1: tuple = ("2010-12", "2011-11")

    repeat_window_days: int = 90
    tie_out_tolerance_gbp: float = 0.01
    top_n_products: int = 10


DEFAULT = Config()
