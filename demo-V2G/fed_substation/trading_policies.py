from datetime import timedelta, datetime
from math import isnan


class BoundedCrossoverTrader:

    def __init__(self, auction, short_window: timedelta, long_window: timedelta, ev_buy_iqr_ratio: float):
        self.auction = auction
        self.short_window = short_window
        self.long_window = long_window
        self.short_ma = 0.0
        self.long_ma = 0.0
        self.iqr = 0.0
        self.ev_buy_iqr_ratio = ev_buy_iqr_ratio
        self.ev_buy_threshold_price = float('inf')
        self.ev_sell_threshold_price = float('inf')
        self.pv_sell_price = float('inf')

    def update_averages(self, current_time):
        if not (current_time - self.auction.lmp_history.dropna().index.min()) >= self.long_window:
            return False
        self.long_ma = self.auction.lmp_history["lmp_mean_since"][current_time - self.long_window]
        self.short_ma = self.auction.lmp_history["lmp_mean_since"][current_time - self.short_window]
        self.iqr = self.auction.lmp_history["lmp_iqr_since"][current_time - self.long_window]
        assert not isnan(self.long_ma), "longma is nan"
        return True

    def formulate_ev_bids(self, current_time: datetime, ev_buy_range):
        if ev_buy_range[0] > 0:
            print("MUST BUY")
            return [["buyer", float('inf'), ev_buy_range[0]]]
        if ev_buy_range[1] < 0:
            print("MUST SELL")
            return [["seller", 0, ev_buy_range[1]]]

        if not self.update_averages(current_time):
            return []

        self.ev_buy_threshold_price = self.long_ma - self.iqr * self.ev_buy_iqr_ratio
        self.ev_sell_threshold_price = max(self.ev_buy_threshold_price + 0.05 * self.iqr, self.short_ma + 0.1 * self.iqr)

        buy_bid = [["buyer", self.ev_buy_threshold_price, ev_buy_range[1]]] if ev_buy_range[1] > 0 else []
        sell_bid = [["seller", self.ev_sell_threshold_price, -ev_buy_range[0]]] if -ev_buy_range[0] > 0 else []
        return buy_bid + sell_bid

    def formulate_bids(self, house_name, current_time: datetime, ev_buy_range, pv_max_power):
        ev_bids = self.formulate_ev_bids(current_time, ev_buy_range) if ev_buy_range else []
        ev_sell_prices = [bid[1] for bid in ev_bids if bid[0] == "seller"]
        # ev_sell_price = min(ev_sell_prices) if ev_sell_prices else float('inf')
        # self.pv_sell_price = min(self.auction.lmp * 0.9, self.ev_sell_threshold_price * 0.95)
        self.pv_sell_price = 0.0148
        pv_bids = [[(house_name, "pv"), "seller", self.pv_sell_price, pv_max_power]] if pv_max_power > 0 else []
        return [[(house_name, "ev")] + bid for bid in ev_bids] + pv_bids
