import os
import pickle
from collections.abc import Sequence
from datetime import datetime
from os.path import splitext, basename
from pathlib import Path
from sys import argv
from time import time as millis, time

import numpy as np
import pandas
from plotly.subplots import make_subplots


def key_collection(c, c_keys, default=None):
    vals = c.values() if isinstance(c, dict) else c
    nn = lambda x, d: d if x is None else x

    if c_keys[0] == "values":
        return [deep_get(x, c_keys[1:]) for x in vals]
    elif c_keys[0] == "sum":
        return sum(deep_get(x, c_keys[1:]) or 0 for x in vals)
    elif c_keys[0] == "mean":
        return np.mean([deep_get(x, c_keys[1:]) or 0 for x in vals])
    elif c_keys[0] == "max":
        return np.max([nn(deep_get(x, c_keys[1:]), float('inf')) for x in vals])
    elif c_keys[0] == "min":
        return np.min([nn(deep_get(x, c_keys[1:]), float('-inf')) or 0 for x in vals])
    else:
        return deep_get(c.get(c_keys[0], default) if isinstance(c, dict) else c[int(c_keys[0])], c_keys[1:])


def deep_get(target, keys, default=None):
    # print("invoke", target, keys)
    keys = keys.split(".") if isinstance(keys, str) else keys
    if target is None:
        return default
    if len(keys) == 0:
        return target

    if isinstance(target, dict) or isinstance(target, Sequence):
        return key_collection(target, keys, default)

    return deep_get(getattr(target, keys[0], default), keys[1:])


class HistoryRecorder:
    def __init__(self, target, keys: list[str] | list[list[str]]):
        self.target = target
        self.keys = keys.split(".") if isinstance(keys, str) else keys
        self.times = []
        self.history = []

    def get_state(self):
        state = []
        for key in self.keys:
            try:
                state.append(deep_get(self.target, key, None))
            except Exception as e:
                raise Exception(f"couldn't get key {key}, {e}")
        return state

    def clear(self):
        self.history = []
        self.times = []

    def record(self, time):
        self.times.append(time)
        # self.history.append([deep_get(self.target, key, None) for key in self.keys])
        self.history.append(self.get_state())

    def df(self):
        return pandas.DataFrame(self.history, index=self.times, columns=self.keys)


class SubstationRecorder:
    def __init__(self, grid, houses, auction, out_dir: str):
        self.file_number = 0
        self.out_dir = out_dir
        os.makedirs(self.out_dir, exist_ok=True)
        [f.unlink() for f in Path(out_dir).glob("*") if f.is_file()]

        self.grid_recorder = HistoryRecorder(grid, [
            "measured_load",
            "weather_temp",
            "intended_load",
            "power_cap"
        ])
        self.house_recorder = HistoryRecorder(houses, [
            "values.hvac.air_temp",
            "mean.hvac.air_temp",
            "min.hvac.air_temp",
            "max.hvac.air_temp",

            "values.hvac.measured_load",
            "sum.hvac.measured_load",
            "max.hvac.measured_load",

            "values.hvac.hvac_on",
            "sum.hvac.hvac_on",

            "values.hvac.set_point",
            "mean.hvac.set_point",

            "values.hvac.base_point",
            "mean.hvac.base_point",

            "values.ev.location",

            "values.ev.stored_energy",
            "sum.ev.stored_energy",

            "values.ev.soc",
            "sum.ev.soc",

            "values.ev.desired_charge_rate",
            "sum.ev.desired_charge_rate",

            "values.ev.charging_load",
            "sum.ev.charging_load",

            "values.ev.workplace_charge_rate",
            "sum.ev.workplace_charge_rate",

            "values.ev.measured_load",
            "sum.ev.measured_load",

            "values.ev.load_range",

            "values.pv.measured_power",
            "sum.pv.measured_power",

            "values.pv.desired_power",
            "sum.pv.desired_power",

            "sum.pv.predicted_max_power",
            "values.pv.predicted_max_power",
            # "values.pv.solar_DC_V_out",
            # "values.pv.solar_DC_I_out",

            "values.measured_unresponsive_load",
            "sum.measured_unresponsive_load",

            "values.measured_total_load",
            "sum.measured_total_load",

            "values.intended_load",
            "sum.intended_load",

            "mean.trading_policy.ev_buy_threshold_price",
            "mean.trading_policy.ev_sell_threshold_price",
            "mean.trading_policy.pv_sell_price",
        ])

        self.auction_recorder = HistoryRecorder(auction, [
            "average_price",
            "num_bids",
            "num_buyers",
            "num_sellers",
            "lmp",
            "bids",
            "transactions",
            "response"
        ])

    def record_houses(self, time):
        self.house_recorder.record(time)

    def record_auction(self, time):
        self.auction_recorder.record(time)

    def record_grid(self, time):
        self.grid_recorder.record(time)

    def history(self):
        return {
            "houses": self.house_recorder.df(),
            "auction": self.auction_recorder.df(),
            "grid": self.grid_recorder.df()
        }

    def clear(self):
        self.house_recorder.clear()
        self.auction_recorder.clear()
        self.grid_recorder.clear()

    def save(self):
        save_time = time()
        with open(os.path.join(self.out_dir, f"{self.file_number}.pkl"), "wb") as f:
            pickle.dump(self.history(), f)
        self.file_number += 1
        self.clear()
        print(f"wrote file {self.file_number - 1} in {time() - save_time:3f}s")
        # with open(os.path.join(self.out_dir, f"{self.file_number}.pkl"), "wb") as f:
        #     pickle.dump(self.history(), f)

    @staticmethod
    def load_history(outdir):
        files = sorted([os.path.join(outdir, f) for f in os.listdir(outdir) if f.endswith(".pkl")],
                       key=lambda x: int(splitext(basename(x))[0]))
        dicts = [pickle.load(open(f, "rb")) for f in files]
        res = {
            k: pandas.concat([dict[k] for dict in dicts])
            for k in ["houses", "auction", "grid"]
        }
        print(f"loaded {len(files)} files for {outdir}")
        return res

    @staticmethod
    def make_progress_figure(h: dict, ev_history=None):
        houses = h["houses"]
        auction = h["auction"]
        grid = h["grid"]
        if len(houses) == 0:
            return
        start_time = houses.index[0]
        end_time = houses.index[-1]
        fig = make_subplots(rows=4, cols=1,
                            specs=[[{}], [{}], [{"secondary_y": True}], [{"secondary_y": True}]], shared_xaxes=True)
        # specs=[[{}, {}], [{}, {}], [{"secondary_y": True}, {}], [{"secondary_y": True}, {}]])
        fig.update_layout(width=1000, height=800, xaxis=dict(range=[start_time, end_time]))
        fig.add_traces([
            {
                "type": "scatter",
                "x": houses.index,
                "y": houses["mean.hvac.air_temp"],
                "name": "Mean House Air Temperature",
            },
            {
                "type": "scatter",
                "x": houses.index,
                "y": houses["max.hvac.air_temp"],
                "name": "Max House Air Temperature",
            },
            {
                "type": "scatter",
                "x": houses.index,
                "y": houses["min.hvac.air_temp"],
                "name": "Min House Air Temperature",
            },
            {
                "type": "scatter",
                "x": houses.index,
                "y": houses["mean.hvac.set_point"],
                "name": "Mean HVAC Set Point",
            },
            {
                "type": "scatter",
                "x": grid.index,
                "y": grid["weather_temp"],
                "name": "Weather Temperature",
            },
        ], rows=1, cols=1)

        fig.update_yaxes(title_text="Temperature", row=1, col=1)

        # clipped_hvac = np.clip(houses["sum.hvac.measured_load"], None,
        #                        80000 - houses["sum.ev.charging_load"] - houses["sum.unresponsive_load"])

        fig.add_traces([
            {
                "type": "scatter",
                "x": houses.index,
                "y": houses["sum.pv.measured_power"],
                "name": "Total Solar PV Power Generated",
                "stackgroup": "house_load"
            },
            {
                "type": "scatter",
                "x": houses.index,
                "y": houses["sum.ev.charging_load"],
                "name": "Total EV Charging Load",
                "stackgroup": "house_load"
            },
            {
                "type": "scatter",
                "x": houses.index,
                "y": houses["sum.measured_unresponsive_load"],
                "name": "Total Unresponsive Load",
                "stackgroup": "house_load"
            },
            {
                "type": "scatter",
                "x": houses.index,
                "y": houses["sum.hvac.measured_load"],
                "name": "Total HVAC Load",
                "stackgroup": "house_load"
            },
            {
                "type": "scatter",
                "x": grid.index,
                "y": np.real(grid["measured_load"]),
                "name": "Total Grid Load",
            },
            {
                "type": "scatter",
                "x": houses.index,
                "y": houses["sum.intended_load"],
                "name": "Total Purchased Load",
            },
        ], rows=2, cols=1)

        fig.update_yaxes(title_text="Load", row=2, col=1)

        fig.add_trace(
            {
                "type": "scatter",
                "x": houses.index,
                "y": houses["sum.ev.stored_energy"],
                "name": "Total EV Energy Stored",
            }, row=3, col=1)
        fig.add_trace(
            {
                "type": "scatter",
                "x": houses.index,
                "y": houses["sum.ev.desired_charge_rate"],
                "name": "Total EV Target Charge Load",
            }, row=3, col=1, secondary_y=True)

        fig.add_trace(
            {
                "type": "scatter",
                "x": houses.index,
                "y": houses["sum.ev.charging_load"],
                "name": "EV Charge In",
                "stackgroup": "ev_battery_delta",
                "line": {"width": 0},
            }, row=3, col=1, secondary_y=True)

        ev_battery_delta = houses["sum.ev.stored_energy"].diff()
        driving_load = ev_battery_delta - houses["sum.ev.charging_load"]
        # print(ev_battery_delta)
        # print(driving_load)

        fig.add_trace(
            {
                "type": "scatter",
                "x": houses.index,
                "y": driving_load,
                "name": "EV Driving Out",
                "stackgroup": "ev_battery_delta",
                "line": {"width": 0},
            }, row=3, col=1, secondary_y=True)

        # locs = houses["values.ev.location"].to_list()
        # wp_charge = np.sum(np.array([ev_history[i]["workplace_charge_rate"].to_list() for i in range(30)]).T, axis=1)
        # fig.add_trace(
        #     {
        #         "type": "scatter",
        #         "x": ev_history[0]["time"],
        #         "y": wp_charge,
        #         "name": "EV Workplace Charge In",
        #         "stackgroup": "ev_battery_delta",
        #     }, row=3, col=1, secondary_y=True)

        # se_deriv = houses["sum.ev.stored_energy"].diff()
        # se_deriv = se_deriv.resample("300S", origin=houses.index.min()).mean() / 15
        #
        # fig.add_trace(
        #     {
        #         "type": "scatter",
        #         "x": se_deriv.index,
        #         "y": se_deriv,
        #         "name": "EV Delta",
        #     }, row=3, col=1, secondary_y=True)

        fig.update_yaxes(title_text="Energy", row=3, col=1)  # , range=[0, max(houses["sum.ev.stored_energy"])])
        fig.update_yaxes(title_text="Power", row=3, col=1, secondary_y=True)  # ,
        #                         range=[min(houses["sum.ev.desired_charge_rate"]), max(houses["sum.ev.desired_charge_rate"])])

        fig.add_trace(
            {
                "type": "scatter",
                "x": auction.index,
                "y": auction["average_price"],
                "name": "Average Price",
            }, row=4, col=1, secondary_y=True)
        fig.add_trace(
            {
                "type": "scatter",
                "x": auction.index,
                "y": auction["lmp"],
                "name": "Local Marginal Price",
            }, row=4, col=1, secondary_y=True)
        # print(houses["mean.trading_policy.buy_threshold_price"])
        fig.add_trace(
            {
                "type": "scatter",
                "x": houses.index,
                "y": houses["mean.trading_policy.ev_buy_threshold_price"],
                "name": "Mean Buy Threshold",
            }, row=4, col=1, secondary_y=True)
        fig.add_trace(
            {
                "type": "scatter",
                "x": houses.index,
                "y": houses["mean.trading_policy.ev_sell_threshold_price"],
                "name": "Mean Sell Threshold",
            }, row=4, col=1, secondary_y=True)
        fig.add_traces([
            {
                "type": "scatter",
                "x": auction.index,
                "y": auction[f"num_{key}"] / auction[f"num_bids"],
                "name": name,
                "stackgroup": "role"
            } for key, name in [("buyers", "Buyers"), ("sellers", "Sellers")]
        ], rows=4, cols=1)
        # fig.add_trace(
        #     {
        #         "type": "scatter",
        #         "x": auction.index,
        #         "y": auction["fraction_buyers_cleared"],
        #         "name": "Fraction Buyers Cleared",
        #     }, row=4, col=1)
        # fig.add_trace(
        #     {
        #         "type": "scatter",
        #         "x": auction.index,
        #         "y": auction["fraction_sellers_cleared"],
        #         "name": "Fraction Sellers Cleared",
        #     }, row=4, col=1)
        print(auction)
        fig.update_yaxes(title_text="Count", row=4, col=1)
        fig.update_yaxes(title_text="Price", row=4, col=1, secondary_y=True)

        return fig
    #
    # @staticmethod
    # def make_figure_solo(h: dict, path):
    #     houses = h["houses"]
    #     # bids = h["bids"]
    #     auction = h["auction"]
    #     grid = h["grid"]
    #     s = millis()
    #     fig = make_subplots(rows=4, cols=1, specs=[[{}], [{}], [{"secondary_y": True}], [{"secondary_y": True}]])
    #     fig.add_trace(
    #         {
    #             "type": "scatter",
    #             "x": auction.index,
    #             "y": auction["average_price"],
    #             "name": "Average Price",
    #         }, row=4, col=1, secondary_y=True)
    #     fig.add_trace(
    #         {
    #             "type": "scatter",
    #             "x": houses.index,
    #             "y": houses["F0_house_A0.trading_policy.long_ma"],
    #             "name": "Long MA",
    #         }, row=4, col=1, secondary_y=True)
    #     fig.add_trace(
    #         {
    #             "type": "scatter",
    #             "x": houses.index,
    #             "y": houses["F0_house_A0.trading_policy.short_ma"],
    #             "name": "Short MA",
    #         }, row=4, col=1, secondary_y=True)
    #     fig.add_trace(
    #         {
    #             "type": "scatter",
    #             "x": houses.index,
    #             "y": houses["F0_house_A0.trading_policy.iqr"],
    #             "name": "IQR",
    #         }, row=4, col=1, secondary_y=True)
    #
    #     # print(houses["F0_house_A0.trading_policy.should_buy"])
    #     # print(houses["F0_house_A0.trading_policy.should_sell"])
    #
    #     # fig.add_trace(
    #     #     {
    #     #         "type": "scatter",
    #     #         "x": houses.index,
    #     #         "y": houses["F0_house_A0.hvac.hvac_on"].apply(lambda x: int(x)),
    #     #         "name": "HVAC On",
    #     #     }, row=4, col=1)
    #
    #     fig.update_yaxes(title_text="Count", row=4, col=1)
    #     fig.update_yaxes(title_text="Price", row=4, col=1, secondary_y=True)
    #
    #     fig.write_image(f"metrics/{path}.svg")
    #     fig.write_html(f"metrics/{path}.html")
    #     print(f"wrote figure in {(millis() - s) * 1000:3f}ms")
    #
    # @staticmethod
    # def make_figure_bids(h: dict, path):
    #     houses = h["houses"]
    #     bids = h["bids"]
    #     auction = h["auction"]
    #     grid = h["grid"]
    #     fig = make_subplots(rows=3, cols=1,
    #                         specs=[[{}], [{}], [{"secondary_y": True}]])
    #     prices = []
    #     for t, bids_round in bids["values.bid.values"].items():
    #         bids_round = pandas.DataFrame(bids_round,
    #                                       columns=["price", "quantity", "hvac_needed", "role", "unresp_load", "name",
    #                                                "base_covered"])
    #         sellers = bids_round[bids_round["role"] == "seller"]
    #         buyers = bids_round[bids_round["role"] == "buyer"]
    #         prices.append([sellers["price"].min(), sellers["price"].mean(), sellers[
    #             "price"].max(), buyers["price"].min(), buyers["price"].mean(), buyers[
    #                            "price"].max()])
    #
    #     prices = pandas.DataFrame(prices, columns=["min_seller_price", "avg_seller_price", "max_seller_price",
    #                                                "min_buyer_price", "avg_buyer_price", "max_buyer_price"],
    #                               index=bids.index)
    #
    #     fig = make_subplots(rows=4, cols=1,
    #                         specs=[[{}], [{}], [{"secondary_y": True}], [{"secondary_y": True}]])
    #
    #     for name in ["min_seller_price", "avg_seller_price", "max_seller_price",
    #                  "min_buyer_price", "avg_buyer_price", "max_buyer_price"]:
    #         fig.add_trace(
    #             {
    #                 "type": "scatter",
    #                 "x": prices.index,
    #                 "y": prices[name],
    #                 "name": name,
    #             }, row=1, col=1)
    #
    #     fig.add_trace(
    #         {
    #             "type": "scatter",
    #             "x": auction.index,
    #             "y": auction["average_price"],
    #             "name": "Average Price",
    #         }, row=2, col=1)
    #
    #     fig.add_trace(
    #         {
    #             "type": "scatter",
    #             "x": auction.index,
    #             "y": auction["num_sellers"],
    #             "name": "Sellers",
    #         }, row=3, col=1)
    #     fig.add_trace(
    #         {
    #             "type": "scatter",
    #             "x": auction.index,
    #             "y": auction["num_buyers"],
    #             "name": "Buyers",
    #         }, row=3, col=1)
    #
    #     fig.write_image(f"{path}.svg")
    #     fig.write_html(f"{path}.html")

    def save_progress_figure(self, make_html=False):
        s = millis()
        fig = self.make_progress_figure(self.history())

        fig.write_image(f"figures/progress.svg")
        if make_html:
            fig.write_html(f"figures/progress.html")

        print(f"wrote figure in {(millis() - s) * 1000:3f}ms")

if __name__ == "__main__":
    history = SubstationRecorder.load_history(f"metrics/{argv[1]}")
    ev_history = pickle.load(open(f"../fed_ev/{argv[1]}_ev_history.pkl", "rb"))

    # SubstationRecorder.make_figure_bids(history, "bids_metrics")
    SubstationRecorder.make_progress_figure(history, make_html=True, ev_history=ev_history)
    # SubstationRecorder.make_figure_solo(history, "solo_metrics")