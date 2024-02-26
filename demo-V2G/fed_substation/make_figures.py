import argparse
import json
import os
import pickle
from datetime import datetime, timedelta, timezone
from os import listdir
from sys import argv
from time import time as millis

import numpy as np
import pandas as pd
from pandas import DataFrame, Series
from plotly.subplots import make_subplots
import plotly
from scipy.integrate import trapezoid

from recording import SubstationRecorder
colors = {
             k: plotly.colors.qualitative.Plotly[i] for i, k in enumerate(["pv", "ev", "grid", "hvac", "unresp"])
         } | {
             "total": "black"
         }

ev_driving_power_all = pickle.load(open("../fed_ev/driving_power.pkl", "rb"))
ev_driving_power_all = ev_driving_power_all.tz_localize("UTC-08:00")

START_TIME = None
END_TIME = None

def rate_integ(series):
    total_s = (series.index.max() - series.index.min()).total_seconds()
    seconds = (series.index - series.index.min()).total_seconds()
    trap = trapezoid(y=series.values, x=seconds)
    return trap / total_s


def take_changes_only(series: Series):
    # return series[~series.index.duplicated(keep="last")]
    last_row = pd.Series(False, index=series.index)
    last_row.iloc[-1] = True
    mask = (series != series.shift()) | last_row
    return series[mask]


def shift(series: Series, offset=-1, res=300):
    idx = pd.date_range(START_TIME, END_TIME, freq=f'{res}S').repeat(2)[1:-1]
    adj = series.set_axis(series.index + timedelta(seconds=offset))
    adj = adj.resample(f'{res}S', origin=START_TIME).first().repeat(2).loc[START_TIME:]
    adj = adj.set_axis(idx)
    return adj
    # .reindex(index=idx, method="ffill")
    # .reindex(index=idx.repeat(2)[1:-1], method="ffill")


def load_plot(h, ev_driving_power):
    print("Generating load/supply plots")
    # qa = h["houses"]["sum.pv.measured_power"]
    # print(f"S1\n{qa[qa.index>= START_TIME+timedelta(hours=10,minutes=0)]}")
    solar_supply = -h["houses"]["sum.pv.measured_power"].map(np.real)
    solar_supply = solar_supply[~solar_supply.index.duplicated(keep="last")]
    solar_supply = shift(solar_supply, offset=0)

    grid_supply = h["grid"]["measured_load"].map(np.real)

    grid_supply = shift(grid_supply)

    unresp_load = shift(h["houses"]["sum.measured_unresponsive_load"])
    hvac_load = shift(h["houses"]["sum.hvac.measured_load"])

    supply_breakdown = make_subplots(rows=1, cols=1)

    w_to_kwhd = lambda x: x / 1000 * 24

    # ev_stored_energy = h["houses"]["sum.ev.stored_energy"]
    # print(ev_stored_energy)
    # ev_charging_load = h["houses"]["sum.ev.charging_load"]
    # print(ev_charging_load)
    # driving_power = pickle.load("../fed_ev/driving_power.pkl")
    # print(driving_power)
    hvac_rate = rate_integ(hvac_load)
    print(f"Average HVAC Load {hvac_rate} W = {w_to_kwhd(hvac_rate)} kWh/day")
    unresp_rate = rate_integ(unresp_load)
    print(f"Average Unresp Load {unresp_rate} W = {w_to_kwhd(unresp_rate)} kWh/day")

    driving_rate = rate_integ(ev_driving_power)
    print(f"Average Driving Load {driving_rate}")
    total_rate = unresp_rate + hvac_rate
    print(f"Average Total Load without driving {total_rate} W = {w_to_kwhd(total_rate)} kWh/day")
    print(
        f"Average Total Load WITH driving {total_rate + driving_rate} W = {w_to_kwhd(total_rate + driving_rate)} kWh/day")

    pv_rate = rate_integ(solar_supply)
    print(f"Average PV Supply {pv_rate} W = {w_to_kwhd(pv_rate)} kWh/day")

    ev_supply = -h["houses"]["values.ev.measured_load"].apply(
        lambda loads: sum(np.real(l) for l in loads if l is not None and np.real(l) < 0))
    ev_load = h["houses"]["values.ev.measured_load"].apply(
        lambda loads: sum(np.real(l) for l in loads if l is not None and np.real(l) > 0))

    ev_supply = shift(ev_supply)
    ev_load = shift(ev_load)

    ev_load_capacity = h["houses"]["values.ev.load_range"].apply(
        lambda ranges: sum(r[1] for r in ranges if r is not None and r[1] >= 0))

    ev_desired_supply = -h["houses"]["values.ev.desired_charge_rate"].apply(
        lambda loads: sum(l for l in loads if l is not None and l < 0))
    ev_desired_load = h["houses"]["values.ev.desired_charge_rate"].apply(
        lambda loads: sum(l for l in loads if l is not None and l > 0))
    grid_cap = h["grid"]["power_cap"]
    pv_capacity = h["houses"]["sum.pv.predicted_max_power"][
        ~h["houses"]["sum.pv.predicted_max_power"].index.duplicated(keep="last")]

    pv_average_capacity = rate_integ(pv_capacity)
    print(f"PV Capacity Average: {pv_average_capacity} = {w_to_kwhd(pv_average_capacity)} kWh/day")

    grid_cap_average = rate_integ(grid_cap)
    print(f"Grid Capacity Average: {grid_cap_average} = {w_to_kwhd(grid_cap_average)} kWh/day")

    pv_surp = pv_average_capacity - rate_integ(solar_supply)
    print(f"PV Surplus: {pv_surp} = {w_to_kwhd(pv_surp)} kWh/day")

    grid_is_capped = grid_cap[0] < 190000
    has_pv = pv_average_capacity > 0
    has_ev = sum(h["houses"]["values.ev.desired_charge_rate"].apply(
        lambda loads: sum(abs(l) for l in loads if l is not None))) > 0
    supplies = [("Grid Supply", grid_supply, colors["grid"])]
    if has_pv:
        supplies += [("PV Supply", solar_supply, colors["pv"])]
    if has_ev:
        supplies += [("EV Supply", ev_supply, colors["ev"])]

    supply_breakdown.add_traces([
        {
            "type": "scatter",
            "x": supply.index,
            "y": supply,
            "name": f"{name}",
            "line": {"width": 0, "color": color},
            "stackgroup": "supply",
            "showlegend": True
        } for name, supply, color in supplies], rows=1, cols=1)

    total_load = unresp_load + hvac_load + ev_load
    print(f"Total Load Range: {max(total_load) - min(total_load)}")
    # supply_breakdown.add_trace({
    #     "type": "scatter",
    #     "x": total_load.index,
    #     "y": total_load,
    #     "name": f"Total Load",
    #     "line": {"color": colors["total"], "width": 1},
    # }, row=1, col=1)

    # grid_cap = pd.Series(np.ones_like(h["grid"].index, dtype=float) * grid_power_cap, index=h["grid"].index)

    capacities = []
    if has_pv:
        capacities += [("PV Supply Capacity", pv_capacity, colors["pv"])]

    if grid_is_capped:
        capacities += [("Grid Supply Capacity", grid_cap, colors["grid"])]

    supply_breakdown.add_traces([
        {
            "type": "scatter",
            "x": supply.index,
            "y": supply,
            "name": f"{name}",
            "line": {"width": 2, "color": color, "dash": "dash"},
            "showlegend": True
        } for name, supply, color in capacities
    ], rows=1, cols=1)

    supply_breakdown.update_xaxes(title_text="", row=1, col=1, tickformat="%H:%M")
    supply_breakdown.update_yaxes(title_text="Power (W)", row=1, col=1, rangemode="tozero")

    supply_pv_only = make_subplots(rows=1, cols=1)
    supply_pv_only.add_trace(
        {
            "type": "scatter",
            "x": solar_supply.index,
            "y": solar_supply,
            "name": "PV Supply",
            "line": {"width": 0, "color": colors["pv"]},
            "stackgroup": "supply",
            "showlegend": True
        }, row=1, col=1)

    supply_pv_only.add_trace(
        {
            "type": "scatter",
            "x": pv_capacity.index,
            "y": pv_capacity,
            "name": "PV Capacity",
            "line": {"width": 2, "color": colors["pv"], "dash": "dash"},
            "showlegend": True
        }, row=1, col=1)

    load_breakdown = make_subplots(rows=1, cols=1)

    loads = [("Unresponsive Load", unresp_load, colors["unresp"]),
             ("HVAC Load", hvac_load, colors["hvac"])]
    if has_ev:
        loads += [("EV Load", ev_load, colors["ev"])]
    load_breakdown.add_traces([
        {
            "type": "scatter",
            "x": load.index,
            "y": load,
            "name": f"{name}",
            "line": {"width": 0, "color": color},
            "stackgroup": "load",
            "showlegend": True
        } for name, load, color in loads], rows=1, cols=1)

    total_supply = grid_supply + solar_supply + ev_supply

    # load_breakdown.add_trace({
    #     "type": "scatter",
    #     "x": total_supply.index,
    #     "y": total_supply,
    #     "name": f"Total Supply",
    #     "line": {"color": colors["total"], "width": 1},
    # }, row=1, col=1)

    if has_ev:
        load_breakdown.add_trace({
            "type": "scatter",
            "x": ev_load_capacity.index,
            "y": ev_load_capacity,
            "name": "EV Load Capacity",
            "showlegend": True,
            "line": {"width": 2, "color": colors["ev"], "dash": "dash"}
        })
    # load_breakdown.add_traces([
    #     {
    #         "type": "scatter",
    #         "x": load.index,
    #         "y": load,
    #         "name": f"{name}",
    #         "line": {"width": 2, "color": color, "dash": "dash"}
    #     } for name, load, color in [
    #         # ("Intended Grid Load", h["houses"]["sum.intended_load"], "red"),
    #         ("EV Load Capacity", ev_load_capacity, colors["ev"]),
    #         # ("Driving Power", ev_load_capacity, colors["ev"])
    #     ]
    # ], rows=1, cols=1)
    load_breakdown.update_xaxes(title_text="", row=1, col=1, tickformat="%H:%M")
    load_breakdown.update_yaxes(title_text="Power (W)", row=1, col=1, rangemode="tozero")
    layout(supply_breakdown, 1200, 400)
    layout(load_breakdown, 1200, 400)
    return supply_breakdown, load_breakdown, has_ev, has_pv, supply_pv_only
    # return fig


def hvac_plot(day_means, h):
    print("Generating HVAC plot")
    hvac = make_subplots(rows=1, cols=1, specs=[[{"secondary_y": True}]])

    ftoc = lambda x: (x - 32) * 5 / 9
    setpoints = h["houses"]["values.hvac.set_point"].apply(lambda x: Series(ftoc(np.array(x))))
    airtemps = h["houses"]["values.hvac.air_temp"].apply(lambda x: Series(ftoc(np.array(x))))
    diffs = np.maximum(airtemps - setpoints, 0)
    diffs_sq = np.power(diffs, 2)
    mean_diffs_sq = diffs_sq.mean(axis=1)
    # mean_diffs_sq = df_days_mean(DataFrame({"diffs": mean_diffs_sq}), True)
    # mean_diffs_sq = DataFrame({"diffs": mean_diffs_sq})
    hvac.add_traces([
        {
            "type": "scatter",
            "x": quant.index,
            "y": quant,
            "name": f"{name}",
        } for name, quant in [
            ("Min House Air Temp", take_changes_only(ftoc(day_means["houses"]["min.hvac.air_temp"]))),
            ("Max House Air Temperature", take_changes_only(ftoc(day_means["houses"]["max.hvac.air_temp"]))),
            ("Mean House Air Temperature", take_changes_only(ftoc(day_means["houses"]["mean.hvac.air_temp"]))),
            ("Mean House Set Point", take_changes_only(ftoc(day_means["houses"]["mean.hvac.set_point"]))),
            ("Weather Temperature", take_changes_only(ftoc(day_means["grid"]["weather_temp"]))),
        ]
    ], rows=1, cols=1)

    hvac.add_trace(
        {
            "type": "scatter",
            "x": mean_diffs_sq.index,
            "y": mean_diffs_sq,
            "name": "$\mkern 1.5mu\overline{\mkern-1.5mu T_{excess}^2 \mkern-1.5mu}(t)\mkern 1.5mu$",
            # "line": {"dash": "dash"},
            "line": {"width": 0},
            "stackgroup": "texcess",
            "showlegend": True
        }, row=1, col=1, secondary_y=True
    )

    # seconds_diff = mean_diffs_sq.index.to_series().diff().fillna(pd.Timedelta(seconds=0)).dt.total_seconds()
    # weighted_sum = (mean_diffs_sq * seconds_diff).sum()
    # total_time = seconds_diff.sum()
    # time_weighted_mean2 = weighted_sum / total_time
    # print("tt2", time_weighted_mean2)
    # seconds = (mean_diffs_sq.index - START_TIME).to_series().dt.total_seconds()
    # print(seconds)
    # time_weighted_mean = trapezoid(y=mean_diffs_sq, x=seconds.values)
    # print(time_weighted_mean)
    # print(time_weighted_mean/max())

    # print(f"TexcessSq: {time_weighted_mean/max(seconds)}")
    print(f"TexcessSq: {rate_integ(mean_diffs_sq)}")
    hvac.update_xaxes(title_text="", row=1, col=1, tickformat="%H:%M")
    hvac.update_yaxes(title_text="Temperature (°C)", row=1, col=1)
    hvac.update_yaxes(title_text=r"$\mkern 1.5mu\overline{\mkern-1.5mu T_{excess}^2 \mkern-1.5mu}(t)\mkern 1.5mu$",
                      row=1,
                      col=1, secondary_y=True)
    layout(hvac, 1200, 400)
    return hvac


def price_plot(a, h, has_ev, has_pv):
    print("Generating price plot")
    price = make_subplots(rows=1, cols=1)

    prices = [("LMP", a["auction"]["lmp"]),
              ("VWAP", a["auction"]["average_price"])]
    if has_ev:
        prices += [("Mean EV Sell Price", h["houses"]["mean.trading_policy.ev_sell_threshold_price"]),
                   ("Mean EV Buy Price", h["houses"]["mean.trading_policy.ev_buy_threshold_price"])]

    if has_pv:
        prices += [("Mean PV Sell Price", h["houses"]["mean.trading_policy.pv_sell_price"])]

    price.add_traces([
        {
            "type": "scatter",
            "x": quant.index,
            "y": quant,
            "name": f"{name}",
        } for name, quant in prices
    ], rows=1, cols=1)

    price.update_xaxes(title_text="", row=1, col=1, tickformat="%H:%M")
    price.update_yaxes(title_text="Price ($)", row=1, col=1)
    layout(price, 1200, 400)
    mean_vwap = a["auction"]["average_price"].mean()
    print(f"Mean VWAP: {mean_vwap}")
    return price


def ev_plot(h):
    print("Generating EV plot")
    # ev = make_subplots(rows=2, cols=1, specs=[[{"secondary_y": True}], [{}]])
    ev = make_subplots(rows=1, cols=1, specs=[[{"secondary_y": True}]])
    idx = pd.date_range(h["houses"].index[0], h["houses"].index[-1], freq=f'300S')
    stored_energy = take_changes_only(h["houses"]["sum.ev.stored_energy"])
    stored_energy = stored_energy.reindex(idx, method="ffill")
    energy_delta = stored_energy.diff()
    seconds = (stored_energy.index - stored_energy.index[0]).total_seconds().to_series().set_axis(energy_delta.index)
    total_power = (energy_delta / seconds.diff()).shift(-1)
    total_power = total_power[:-1].repeat(2).set_axis(idx.repeat(2)[1:-1])
    # print(total_power)
    charging_load = h["houses"]["sum.ev.charging_load"]
    charging_load = charging_load[~charging_load.index.duplicated(keep="last")]
    charging_load = charging_load.reindex(idx, method="ffill")
    # print(charging_load)
    charging_load = charging_load[:-1].repeat(2).set_axis(idx.repeat(2)[1:-1])
    driving_power = total_power - charging_load
    # print(driving_power)

    ev.add_traces([
        {
            "type": "scatter",
            "x": quant.index,
            "y": quant,
            "name": f"{name}",
            # "line": {"dash": "dash"},
            "line": {"width": 0},
            "stackgroup": "load",
            "showlegend": True
        } for name, quant in [
            ("Driving Power", -driving_power),
            ("Charging/Discharging Power", charging_load),
        ]
    ], rows=1, cols=1)
    # ev.add_trace(
    #     {
    #         "type": "scatter",
    #         "x": DRIVING_POWER.index,
    #         "y": -DRIVING_POWER,
    #         "name": f"DP2",
    #         "line": {"color": colors["total"], "width": 1},
    #         "showlegend": True
    #     }, row=1, col=1
    # )
    ev.add_trace(
        {
            "type": "scatter",
            "x": total_power.index,
            "y": total_power,
            "name": f"Total Battery Load",
            "line": {"color": colors["total"], "width": 1},
            "showlegend": True
        }, row=1, col=1
    )
    # ev.add_trace(
    #     {
    #         "type": "scatter",
    #         "x": h["houses"]["sum.ev.charging_load"].index,
    #         "y": h["houses"]["sum.ev.charging_load"],
    #         "name": f"Charging/Discharging Power Raw",
    #         "showlegend": True
    #     }, row=1, col=1
    # )

    ev.add_trace(
        {
            "type": "scatter",
            "x": stored_energy.index,
            "y": stored_energy,
            "name": f"Total Battery Stored Energy",
            "showlegend": True
        }, row=1, col=1, secondary_y=True
    )

    ev.update_xaxes(title_text="", row=1, col=1, tickformat="%H:%M")
    ev.update_yaxes(title_text="Power (W)", row=1, col=1)
    ev.update_yaxes(title_text="Energy (J)", row=1, col=1, secondary_y=True)

    # driving_count = h["houses"]["values.ev.location"].apply(lambda ls: ls.count("driving"))
    # ev.add_trace(
    #     {
    #         "type": "scatter",
    #         "x": driving_count.index,
    #         "y": driving_count,
    #         "name": f"EVs Driving",
    #         "showlegend": True
    #     }, row=2, col=1
    # )

    layout(ev, 1200, 400)
    return ev


def market_curves_plot(auction):
    times = [datetime.strptime(d, '%Y-%m-%d %H:%M:%S %z') for d in [
        '2013-07-05 00:00:00 -0800',
        '2013-07-05 06:00:00 -0800',
        '2013-07-05 12:00:00 -0800',
        '2013-07-05 18:00:00 -0800']]
    market = make_subplots(rows=1, cols=len(times), shared_yaxes=True, shared_xaxes=True)
    for i, (t, bids) in enumerate(auction["bids"].loc[times].items()):
        prices = sorted(bids["price"].unique())
        buys = bids[bids["role"] == "buyer"]
        bought_at_price = [buys[buys["price"] >= p]["quantity"].sum() for p in prices]

        sells = bids[bids["role"] == "seller"]
        sold_at_price = [sells[sells["price"] <= p]["quantity"].sum() for p in prices]
        market.add_trace({
            "type": "scatter",
            "x": prices,
            "y": bought_at_price,
            "name": f"Buyers {t}",
            "showlegend": True
        }, row=1, col=i + 1)
        market.add_trace({
            "type": "scatter",
            "x": prices,
            "y": sold_at_price,
            "name": f"Sellers {t}",
            "showlegend": True
        }, row=1, col=i + 1)
    return market


def oneplot(h, keys, scenario_name, ax_names):
    has_y2 = any([axis for _, _, axis, _, _, _ in keys])
    fig = make_subplots(rows=1, cols=1, specs=[[{"secondary_y": has_y2}]])
    print(keys)
    for varnum, (table, key, axis, name, stackgroup, scale) in enumerate(keys):
        print(
            f"{name}: min={h[table][key].min()}, max={h[table][key].max()}, mean={h[table][key].mean()} range={h[table][key].max() - h[table][key].min()}")
        fig.add_trace(
            {
                "type": "scatter",
                "x": h[table][key].index,
                "y": h[table][key].map(scale) if scale else h[table][key],
                "name": f"{name}",
                "line": {"color": colors[varnum], "width": 0 if stackgroup else 2},
                "stackgroup": stackgroup,
            }, row=1, col=1, secondary_y=axis)

    fig.update_xaxes(title_text="Time", row=1, col=1, tickformat="%H:%M")
    fig.update_yaxes(title_text=ax_names[0], row=1, col=1, rangemode="tozero")
    if len(ax_names) > 1:
        fig.update_yaxes(title_text=ax_names[1], row=1, col=1, secondary_y=True)
    return fig


def sameplot(hs, keys, scenario_names, ax_names):
    has_y2 = any([axis for _, _, axis, _ in keys])
    fig = make_subplots(rows=1, cols=1, shared_xaxes=True, specs=[[{"secondary_y": has_y2}]])
    for varnum, (table, key, axis, name) in enumerate(keys):
        fig.add_traces([
            {
                "type": "scatter",
                "x": h[table].index,
                "y": h[table][key],
                "name": f"{scenario_names[i]}",
                "legendgroup": name,
                "legendgrouptitle_text": name,
                "line": {"color": colors[i], "width": 2},
            }
            for i, h in enumerate(hs)
        ], rows=1, cols=1, secondary_ys=[axis] * len(hs))
    fig.update_xaxes(title_text="Time", row=1, col=1)
    fig.update_yaxes(title_text=ax_names[0], row=1, col=1)
    if len(ax_names) > 1:
        fig.update_yaxes(title_text=ax_names[1], row=1, col=1, secondary_y=True)
    return fig


def multiplot(hs, keys, scenario_names, ax_names, layout, size=1000):
    rows, cols = layout
    has_y2 = any([axis for _, _, axis, _ in keys])
    specs = [
        [
            {"secondary_y": has_y2} for col in range(cols)
        ] for row in range(rows)
    ]
    # print(specs)
    fig = make_subplots(rows=rows, cols=cols, shared_xaxes=True, specs=specs, subplot_titles=scenario_names)
    for i, h in enumerate(hs):
        row, col = i // cols, i % cols
        for varnum, (table, key, axis, name) in enumerate(keys):
            print(
                f"{name}: min={h[table][key].min()}, max={h[table][key].max()}, mean={h[table][key].mean()}, range={h[table][key].max() - h[table][key].min()}}}")
            fig.add_traces([
                {
                    "type": "scatter",
                    "x": h[table].index,
                    "y": h[table][key],
                    "name": name,
                    "line": {"color": colors[varnum], "width": 2},
                    "showlegend": i == 0,
                }
            ], rows=row + 1, cols=col + 1, secondary_ys=[axis] * len(hs))

        fig.update_xaxes(title_text="Time", row=row + 1, col=col + 1)
        fig.update_yaxes(title_text=ax_names[0], row=row + 1, col=col + 1)
        if len(ax_names) > 1:
            fig.update_yaxes(title_text=ax_names[1], row=row + 1, col=col + 1, secondary_y=True)

    return fig


def df_days_mean(df: DataFrame, resample=False):
    groups = list(df.groupby(df.index.dayofyear))
    stack = pd.concat([df.set_index(df.index.time) for doy, df in groups])
    means = stack.groupby(stack.index).mean()
    dated = means.set_index(means.index.map(lambda t: datetime.combine(START_TIME.date(), t)))
    if resample:
        dated = dated.resample(timedelta(seconds=300)).mean()
    return dated


def days_mean(hs: list[dict[str: DataFrame]], cols, resample=False):
    hs = [
        {
            k: list(df[cols[k]].groupby(df.index.dayofyear))
            for k, df in h.items() if k in cols
        }
        for h in hs
    ]
    hs = [
        {
            k: pd.concat([df.set_index(df.index.time) for doy, df in groups])
            for k, groups in h.items()
        }
        for h in hs
    ]
    hs = [
        {
            k: stack.groupby(stack.index).mean()
            for k, stack in h.items()
        }
        for h in hs
    ]
    hs = [
        {
            k: ts.set_index(ts.index.map(lambda t: datetime.combine(START_TIME.date(), t)))
            for k, ts in h.items()
        }
        for h in hs
    ]
    if resample:
        hs = [
            {
                k: ts.resample(timedelta(seconds=300)).mean()
                for k, ts in h.items()
            }
            for h in hs
        ]
    return hs


def layout(fig, w=1000, h=500):
    fig.update_layout(
        width=w, height=h, margin=dict(l=0, r=0, t=0, b=0),
        legend=dict(
            orientation="h",
            xanchor="center",
            x=0.5,
            # yanchor="bottom",
            # y=1.02,
            # y=1,
            # traceorder="normal",
        ),
        font=dict(size=18))


def one_figs_capped(hs, name, start_time, end_time):
    print(f"Creating figures for {name}")
    house_means = hs
    ev_driving_power = ev_driving_power_all[(start_time <= ev_driving_power_all.index) & (ev_driving_power_all.index < end_time)]
    ev_driving_power = ev_driving_power[:-1].repeat(2).set_axis(ev_driving_power.index.repeat(2)[1:-1])

    ev = ev_plot(house_means[0])
    ev.write_html(f"figures/{name}_ev.html")
    ev.write_image(f"figures/{name}_ev.png")

    hvac = hvac_plot(house_means[0], hs[0])
    hvac.write_html(f"figures/{name}_hvac.html")
    hvac.write_image(f"figures/{name}_hvac.png", scale=1)

    supply_breakdown, load_breakdown, has_ev, has_pv, supply_pv_only = load_plot(house_means[0], ev_driving_power)
    supply_breakdown.write_html(f"figures/{name}_supply.html")
    supply_breakdown.write_image(f"figures/{name}_supply.png")
    supply_pv_only.write_html(f"figures/{name}_supply_pv.html")
    supply_pv_only.write_image(f"figures/{name}_supply_pv.png")
    load_breakdown.write_html(f"figures/{name}_load.html")
    load_breakdown.write_image(f"figures/{name}_load.png")

    # price_means = days_mean(hs, {
    #     "auction": ["average_price", "lmp"]
    # }, resample=True)
    # price_means = hs

    price = price_plot(house_means[0], house_means[0], has_ev, has_pv)
    price.write_html(f"figures/{name}_price.html")
    price.write_image(f"figures/{name}_price.png", scale=1)
    # print(max(total_l), min(total_l), max(total_l) - min(total_l))


def all_single_figs(dir, start_time, end_time):
    runs = [f for f in listdir(dir)]
    print(f"Creating figures for {runs}")
    for run in runs:
        try:
            print(f"Loading {run}")
            hs = [SubstationRecorder.load_history(f"{dir}/{run}")]
            end_time = min(end_time, hs[0]["houses"].index.max(), hs[0]["houses"].index.max())
            hs = [
                {k: h[k][(start_time <= h[k].index) & (h[k].index < end_time)] for k in h.keys()}
                for h in hs
            ]
            one_figs_capped(hs, run, start_time, end_time)
        except Exception as e:
            print(f"skipping {run}, broken")
            continue


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog='make_figures',
        description='Generate figures showing behaviour of PET system')

    date_type = lambda s: datetime.strptime(s, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone(timedelta(hours=-8)))
    parser.add_argument("-s", "--start_date", type=date_type, default=datetime(2013, 7, 1, 0, 0, 0, tzinfo=timezone(timedelta(hours=-8))))
    parser.add_argument("-e", "--end_date", type=date_type, default=datetime(2013, 7, 8, 0, 0, 0, tzinfo=timezone(timedelta(hours=-8))))
    command_group = parser.add_mutually_exclusive_group()
    command_group.add_argument("-a", "--all", type=str, help="generate figures for all metrics directories in directory")
    command_group.add_argument("-m", "--metrics", type=str, help="generate figures for single metrics directory")

    args = parser.parse_args()
    START_TIME = args.start_date
    END_TIME = args.end_date
    if args.all:
        all_single_figs(args.all, args.start_date, args.end_date)
    elif args.metrics:
        h = SubstationRecorder.load_history(args.metrics)
        hs = [h]
        end_time = min(args.end_date, hs[0]["houses"].index.max(), hs[0]["houses"].index.max())
        hs = [
            {k: h[k][(args.start_date <= h[k].index) & (h[k].index < end_time)] for k in h.keys()}
            for h in hs
        ]
        name = os.path.splitext(os.path.basename(args.metrics))[0]
        one_figs_capped(hs, name, args.start_date, args.end_date)
    #
    # else:
    #     hs = [SubstationRecorder.load_history(f"metrics/{a}") for a in argv[1:]]
    #     end_time = min(args.end_date, hs[0]["houses"].index.max(), hs[0]["houses"].index.max())
    #     hs = [
    #         {k: h[k][(args.start_date <= h[k].index) & (h[k].index < end_time)] for k in h.keys()}
    #         for h in hs
    #     ]
    #     sameplot(hs, [("houses", "sum.hvac.measured_load", False, "HVAC Load")], argv[1:], ["HVAC Load (W)"])
    #     multiplot(hs, [("houses", "sum.hvac.measured_load", False, "HVAC Load")], argv[1:], ["HVAC Load (W)"],
    #               layout=(1, 2))
# ev_history = pickle.load(open(f"../fed_ev/{argv[1]}_ev_history.pkl", "rb"))

# SubstationRecorder.make_figure_bids(history, "bids_metrics")
# fig
# fig_compare(history, argv[1], make_html=True, ev_history=ev_history)
