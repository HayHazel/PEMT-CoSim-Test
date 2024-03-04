import json
from datetime import datetime, timedelta

import numpy as np
import pandas
from helics import HelicsFederate
from pandas import DataFrame, Series
from scipy.stats import iqr


# SELLER ONLY DIVISIBLE
def match_orders(bids):
    buyers = bids[bids["role"] == "buyer"].sample(frac=1).sort_values("price",
                                                                      ascending=False)[
        ["trader", "price", "quantity"]].values
    sellers = bids[bids["role"] == "seller"].sample(frac=1).sort_values("price",
                                                                        ascending=True)[
        ["trader", "price", "quantity"]].values
    assert not any(buyers[:, 1] < 0), "some buyer(s) have negative price"
    assert not any(sellers[:, 1] < 0), "some seller(s) have negative price"
    assert not any(buyers[:, 2] < 0), "some buyer(s) have negative quantity"
    assert not any(sellers[:, 2] < 0), "some seller(s) have negative quantity"
    buyers = buyers[buyers[:, 1] > 0]
    traders = set(trader[0] for trader in bids["trader"])
    transactions = []
    while len(buyers):
        matched_sellers = (buyers[0][1] >= sellers[:, 1]).nonzero()
        excess_sellers = (buyers[0][2] <= np.cumsum(sellers[matched_sellers[0], 2])).nonzero()[0]
        if len(excess_sellers):
            sufficient_sellers = matched_sellers[0][:excess_sellers[0] + 1]
            for i in sufficient_sellers:
                transaction_quantity = min(buyers[0][2], sellers[i][2])
                if transaction_quantity > 0:
                    buyers[0][2] -= transaction_quantity
                    sellers[i][2] -= transaction_quantity
                    transactions.append(
                        {"seller": sellers[i][0], "buyer": buyers[0][0], "quantity": transaction_quantity,
                         "price": sellers[i][1]})
            if buyers[0][2] == 0.0:
                buyers = np.delete(buyers, 0, axis=0)

            sellers = np.array([s for s in sellers if s[2] > 0.0])
        else:  # no sellers can cover buyer order, and buys are indivisible
            buyers = np.delete(buyers, 0, axis=0)

    response = {trader: [] for trader in traders}
    for t in transactions:
        response[t["buyer"][0]].append({
            "price": t["price"],
            "quantity": t["quantity"],
            "role": "buyer",
            "target": t["buyer"][1]
        })
        response[t["seller"][0]].append({
            "price": t["price"],
            "quantity": t["quantity"],
            "role": "seller",
            "target": t["seller"][1]
        })
    # print(json.dumps(response, indent=2))
    return transactions, response


class ContinuousDoubleAuction:
    def __init__(self, helics_federate: HelicsFederate, start_time: datetime):
        self.average_price = 0
        self.lmp = 0.0
        self.refload = 0.0
        self.refload_p = 0.0
        self.refload_q = 0.0
        self.helics_federate = helics_federate
        self.bids: DataFrame = DataFrame()
        self.period = 300
        self.transactions = {}
        self.response = {}

        self.num_bids = 0
        self.num_sellers = 0
        self.num_buyers = 0
        self.num_nontcp = 0

        self.lmp_history = DataFrame({
            "lmp": self.lmp,
            "lmp_mean_since": self.lmp,
            "lmp_median_since": self.lmp,
            "lmp_iqr_since": self.lmp
        }, index=[start_time])

        self.history = DataFrame({
            "average_price": self.average_price,
            "cleared_quantity": 0.0,
            "average_since": self.average_price,
            "iqr_since": 0,
        }, index=[start_time])

        # publications and subscriptions
        if helics_federate is not None:
            self.pubUnresp = helics_federate.publications["pet1/unresponsive_mw"]
            self.pubMax = helics_federate.publications["pet1/responsive_max_mw"]
            self.pubC1 = helics_federate.publications["pet1/responsive_c1"]
            self.pubC2 = helics_federate.publications["pet1/responsive_c2"]
            self.pubDeg = helics_federate.publications["pet1/responsive_deg"]
            self.pub_clearing_price = helics_federate.publications["pet1/clear_price"]

            self.subFeeder = helics_federate.subscriptions["gld1/distribution_load"]
            self.sub_lmp = helics_federate.subscriptions["pypower/LMP_B7"]

    def update_stats(self):
        times = [self.lmp_history.index[-1] - d for d in [timedelta(hours=0.5), timedelta(hours=24)]]

        self.history["average_since"] = Series([
            np.mean(self.history.loc[self.history.index >= i, "average_price"])
            for i in times
        ], index=times)

        self.history["iqr_since"] = Series([
            iqr(self.history.loc[self.history.index >= i, "average_price"])
            for i in times
        ], index=times)

        self.lmp_history["lmp_median_since"] = Series([
            np.median(self.lmp_history.loc[self.lmp_history.index >= i, "lmp"])
            for i in times
        ], index=times)
        self.lmp_history["lmp_mean_since"] = Series([
            np.mean(self.lmp_history.loc[self.lmp_history.index >= i, "lmp"])
            for i in times
        ], index=times)
        self.lmp_history["lmp_iqr_since"] = Series([
            iqr(self.lmp_history.loc[self.lmp_history.index >= i, "lmp"])
            for i in times
        ], index=times)

        # print(f"set lmp his @ {self.lmp_history.index[-1]}\n{self.lmp_history.dropna()}")

    def collect_bids(self, bids):
        # self.substation_seller_bid = [self.lmp, float('inf'), False, "seller", 0, "substation", False]
        self.bids = DataFrame(bids, columns=["trader", "role", "price", "quantity"])
        # print("auction got bids:")
        # print(self.bids.to_string())
        self.num_bids = len(self.bids)
        self.num_sellers = (self.bids["role"] == "seller").sum()
        self.num_buyers = (self.bids["role"] == "buyer").sum()

    def update_refload(self):
        c = self.subFeeder.complex
        self.refload_p = c.real * 0.001
        self.refload_q = c.imag * 0.001
        self.refload = self.refload_p  # math.sqrt(self.refload_p**2 + self.refload_q**2)

    def update_lmp(self, current_time):
        if self.lmp_history.index[-1] == current_time:
            return

        self.lmp = self.sub_lmp.double
        self.lmp_history = pandas.concat([self.lmp_history, DataFrame(
            {"lmp": self.lmp}, index=[current_time])])

    def clear_market(self, current_time: datetime):
        self.transactions, self.response = match_orders(self.bids)
        cleared_quantity = sum(t["quantity"] for t in self.transactions)
        average_price = sum(t["price"] * t["quantity"] for t in self.transactions) / cleared_quantity
        self.average_price = average_price
        # self.pub_clearing_price.publish(self.clearing_price)
        self.history = pandas.concat([self.history, DataFrame(
            {"average_price": self.average_price, "cleared_quantity": cleared_quantity, "lmp": self.lmp},
            index=[current_time])])
        # self.update_stats()
        return self.response


def test_auction(auction: ContinuousDoubleAuction):
    test_bids = [
        [("s1", "a"), "seller", 1.6, float('inf')],
        [("b1", "a"), "buyer", float('inf'), 1600],
    ]
    auction.lmp = 3.0
    auction.collect_bids(test_bids)
    response = auction.clear_market(datetime.now())

    assert response["s1"][0]["quantity"] == 1600.0
    assert response["s1"][0]["role"] == "seller"
    assert response["b1"][0]["quantity"] == 1600.0
    assert response["b1"][0]["role"] == "buyer"

    test_bids = [
        [("s1", "a"), "seller", 1.6, float('inf')],
        [("s2", "a"), "seller", 1.2, float('inf')],
        [("b1", "a"), "buyer", float('inf'), 1600],
    ]
    auction.lmp = 3.0
    auction.collect_bids(test_bids)
    response = auction.clear_market(datetime.now())

    assert len(response["s1"]) == 0
    assert response["s2"][0]["quantity"] == 1600.0
    assert response["s2"][0]["role"] == "seller"
    assert response["b1"][0]["quantity"] == 1600.0
    assert response["b1"][0]["role"] == "buyer"

    test_bids = [
        [("s1", "a"), "seller", 1.6, float('inf')],
        [("s2", "a"), "seller", 1.2, float('inf')],
        [("b1", "a"), "buyer", float('inf'), 1600],
        [("b2", "a"), "buyer", 0, 4000],
        [("b3", "a"), "buyer", 0, 0],
    ]
    auction.lmp = 3.0
    auction.collect_bids(test_bids)
    response = auction.clear_market(datetime.now())
    # assert auction.clearing_price == 1.2
    assert len(response["s1"]) == 0
    assert response["s2"][0]["quantity"] == 1600.0
    assert response["s2"][0]["role"] == "seller"
    assert response["b1"][0]["quantity"] == 1600.0
    assert response["b1"][0]["role"] == "buyer"
    assert len(response["b2"]) == 0
    assert len(response["b3"]) == 0

    test_bids = [
        [("s1", "a"), "seller", 1.6, float('inf')],
        [("s2", "a"), "seller", 1.2, float('inf')],
        [("b1", "a"), "buyer", float('inf'), 1600],
        [("b2", "a"), "buyer", 20, 4000],
        [("b3", "a"), "buyer", 0, 0],
    ]
    auction.lmp = 3.0
    auction.collect_bids(test_bids)
    response = auction.clear_market(datetime.now())
    print(json.dumps(response, indent=2))
    # assert auction.clearing_price == 1.2
    assert len(response["s1"]) == 0
    # assert sum(["quantity"] response["s2"] == 5600.0
    assert response["s2"][0]["role"] == "seller"
    assert response["b1"][0]["quantity"] == 1600.0
    assert response["b1"][0]["role"] == "buyer"
    assert response["b2"][0]["quantity"] == 4000.0
    assert response["b2"][0]["role"] == "buyer"
    assert len(response["b3"]) == 0

    test_bids = [
        ["s1", "seller", 1.6, float('inf')],
        ["s2", "seller", 0.0, 0.0],
        ["s3", "seller", 0.0, 0.0],
        ["s4", "seller", 0.0, 0.0],
        ["s5", "seller", 1.2, float('inf')],
        ["b1", "buyer", float('inf'), 1600],
        ["b2", "buyer", 20, 4000],
        ["b3", "buyer", 0, 0],
    ]
    auction.lmp = 3.0
    auction.collect_bids(test_bids)
    response = auction.clear_market(datetime.now())
    # assert auction.clearing_price == 1.2
    assert len(response["s1"]) == 0

    assert response["s2"][0]["quantity"] == 0.0
    assert response["s2"][0]["role"] == "seller"

    assert response["s3"][0]["quantity"] == 0.0
    assert response["s3"][0]["role"] == "seller"

    assert response["s4"][0]["quantity"] == 0.0
    assert response["s4"][0]["role"] == "seller"

    assert response["s5"][0]["quantity"] == 5600.0
    assert response["s5"][0]["role"] == "seller"

    assert response["b1"][0]["quantity"] == 1600.0
    assert response["b1"][0]["role"] == "buyer"
    assert response["b2"][0]["quantity"] == 4000.0
    assert response["b2"][0]["role"] == "buyer"
    assert len(response["b3"]) == 0

    # more buy than sell

    test_bids = [
        ["s1", "seller", 1.6, 1000],
        ["b2", "buyer", 1.9, 1000],
        ["b3", "buyer", 1.8, 400],
    ]
    auction.lmp = 3.0
    auction.collect_bids(test_bids)
    response = auction.clear_market(datetime.now())
    print(response)
    # assert auction.clearing_price == 1.2
    # assert len(response["s1"]) == 0
    # assert response["s2"][0]["quantity"] == 1600.0
    # assert response["s2"][0]["role"] == "seller"
    # assert response["b1"][0]["quantity"] == 1600.0
    # assert response["b1"][0]["role"] == "buyer"
    # assert len(response["b2"]) == 0
    # assert len(response["b3"]) == 0


if __name__ == "__main__":
    a = ContinuousDoubleAuction(None, datetime.now())
    test_auction(a)
