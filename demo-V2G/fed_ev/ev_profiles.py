import argparse
import collections
import glob
import gzip
import os
import pickle
from collections import namedtuple
from datetime import datetime, timedelta
from math import ceil
from multiprocessing import Pool
from pathlib import Path
from random import choices

import numpy as np
import pandas as pd
from emobpy import Mobility, Consumption, HeatInsulation, BEVspecs, Availability, Charging, ModelSpecs
from emobpy.tools import set_seed
from plotly.subplots import make_subplots

set_seed(seed=200, dir="emobpy_data/config_files")


class DotDict(dict):
    """dot.notation access to dictionary attributes"""
    __getattr__ = lambda self, key: DotDict(self.get(key)) if type(self.get(key)) is dict else self.get(key)
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


STATION_DISTRIBUTION = {
    # charging stations type probability distribution by location
    'prob_charging_point': {
        'errands': {'none': 1},
        'escort': {'none': 1},
        'leisure': {'none': 1},
        'shopping': {'none': 1},
        'home': {'home': 1},
        'workplace': {'workplace': 0.8},
        'driving': {'none': 1}
    },

    'capacity_charging_point': {  # Nominal power rating of charging station in kW
        'public': 22,
        'home': 3.7,
        'workplace': 11,
        'none': 0,  # dummy station
        'fast75': 75,
        'fast150': 150
    }
}

CAR_MODELS_DISTRIBUTION = pd.DataFrame([
    [BEVspecs().model(('Tesla', 'Model Y Long Range AWD', 2020)), 0.6],
    [BEVspecs().model(('Volkswagen', 'ID.3', 2020)), 0.4],
], columns=["car_model", "probability"])

USER_TYPE_DISTRIBUTION = pd.DataFrame([
    [True, True, 0.8],
    [True, False, 0],
    [False, False, 0.2],
], columns=["worker", "full_time", "probability"])

EVProfile = namedtuple("EVProfile", ["mobility", "consumption", "availability", "demand", "car_model"])


def layout(fig, w=None, h=None):
    fig.update_layout(
        width=w or 1000, height=h or 500, margin=dict(l=0, r=0, t=0, b=0),
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


class EVProfiles:
    def __init__(self, start_date: datetime, end_date: datetime, time_step, num_evs, profiles_dir,
                 station_distribution=STATION_DISTRIBUTION, car_models_distribution=CAR_MODELS_DISTRIBUTION,
                 user_type_distribution=USER_TYPE_DISTRIBUTION):
        if station_distribution is None:
            station_distribution = STATION_DISTRIBUTION
        self.consumption_df = None
        self.demand_df = None
        self.start_date = start_date
        self.end_date = end_date
        self.length_hours = ceil((self.end_date - self.start_date).total_seconds() / 3600)
        self.time_step = time_step
        self.num_evs = num_evs
        self.profiles = []
        self.profiles_dir = profiles_dir
        self.car_models_distribution = car_models_distribution
        self.user_type_distribution = user_type_distribution
        self.station_distribution = station_distribution

    def load_from_saved(self):
        if self.num_evs == 0:
            return self
        print(f"Loading {self.num_evs} EV profiles from saved")
        files = glob.glob(f"{self.profiles_dir}/*")
        if len(files) < self.num_evs:
            raise Exception(f"Not enough saved EV profiles. Found {len(files)}, expected {self.num_evs}")
        self.profiles = [pickle.load(gzip.open(f, 'rb')) for f in files[:self.num_evs]]
        self.consumption_df = pd.concat([profile.consumption.timeseries for profile in self.profiles], axis=1,
                                        keys=range(self.num_evs))

        # self.demand_df = pd.concat([profile.demand.timeseries for profile in self.profiles], axis=1,
        #                            keys=range(self.num_evs))

        print(f"Finished loading {self.num_evs} EV profiles from saved:", ", ".join(
            [f"{n}x{m}" for m, n in collections.Counter(p.car_model.name for p in self.profiles).items()]))
        return self

    def clear_profiles_dir(self):
        Path(self.profiles_dir).mkdir(parents=True, exist_ok=True)
        files = glob.glob(f"{self.profiles_dir}/*")
        for f in files:
            os.remove(f)
        print(f"Emptied profiles directory {self.profiles_dir}")

    def run(self, pool_size=2):
        self.profiles = []
        self.clear_profiles_dir()
        models = self.car_models_distribution.sample(n=self.num_evs, weights="probability", replace=True)
        user_types = self.user_type_distribution.sample(n=self.num_evs, weights="probability", replace=True)

        print(f"Generating EV Profiles on {pool_size} threads:", ", ".join(
            [f"{n}x{m.name}" for m, n in collections.Counter(models["car_model"]).items()]))

        with Pool(pool_size) as p:
            self.profiles = p.starmap(self.create_ev_profile,
                                      zip(range(self.num_evs), models["car_model"], user_types["worker"], user_types["full_time"]))

        print("Finished generating EV profiles")
        self.consumption_df = pd.concat([profile.consumption.timeseries for profile in self.profiles], axis=1,
                                        keys=range(self.num_evs))
        # self.demand_df = pd.concat([profile.demand.timeseries for profile in self.profiles], axis=1,
        #                            keys=range(self.num_evs))
        return self.profiles

    def create_ev_profile(self, i, car_model: ModelSpecs, worker: bool, full_time: bool):
        print(f"Creating EV profile {i}, car model {car_model.name}")
        try:
            mobility = self.create_mobility_timeseries(worker, full_time)
            consumption = self.create_consumption_timeseries(mobility, car_model)
            # availability and demand profiles are not used, since the EV federate handles charging/discharging
            # differently

            # availability = self.create_availability_timeseries(consumption)
            # demand = self.create_demand_timeseries(availability)
            result = EVProfile(mobility, consumption, None, None, car_model)
            print(f"EV profile {i} created, saving now")

            with gzip.open(f"{self.profiles_dir}/{i}.pkl", 'wb') as handle:
                pickle.dump(result, handle, protocol=pickle.HIGHEST_PROTOCOL)
            print(f"EV profile {i} saved")
            return result
        except Exception as e:
            print(e)
            print(f"Failed to create mobility timeseries. Retrying...")
            return self.create_ev_profile(i, car_model, worker, full_time)

    def create_mobility_timeseries(self, worker: bool, full_time: bool):
        print(f"Creating mobility timeseries, worker={worker}, full_time={full_time}")
        m = Mobility(config_folder='emobpy_data/config_files')
        m.set_params(
            name_prefix="evprofile",
            total_hours=self.length_hours,  # one week
            time_step_in_hrs=self.time_step,  # 15 minutes
            category="user_defined",
            reference_date=self.start_date.strftime("%Y-%m-%d")
        )

        m.set_stats(
            stat_ntrip_path="TripsPerDay.csv",
            stat_dest_path=f"DepartureDestinationTrip_{'Worker' if worker else 'Free'}.csv",
            stat_km_duration_path="DistanceDurationTrip.csv",
        )
        rule_key = ("fulltime" if full_time else "parttime") if worker else "freetime"
        m.set_rules(rule_key=rule_key)
        m.run()
        print(f"Mobility timeseries created {m.name}")
        return m

    def create_consumption_timeseries(self, mobility: Mobility, car_model: ModelSpecs):
        print(f"Creating consumption timeseries for mobility {mobility.name}")
        c = Consumption(mobility.name, car_model)
        c.load_setting_mobility(DotDict({"db": {mobility.name: mobility.__dict__}}))
        hi = HeatInsulation(True)
        c.run(
            heat_insulation=hi,
            weather_country='DE',
            weather_year=2016,
            passenger_mass=75,  # kg
            passenger_sensible_heat=70,  # W
            passenger_nr=1.5,  # Passengers per vehicle including driver
            air_cabin_heat_transfer_coef=20,  # W/(m2K). Interior walls
            air_flow=0.02,  # m3/s. Ventilation
            driving_cycle_type='WLTC',  # Two options "WLTC" or "EPA"
            road_type=0,  # For rolling resistance, Zero represents a new road.
            road_slope=0
        )
        print(f"Consumption timeseries created {c.name}")
        return c

    def create_availability_timeseries(self, consumption: Consumption):
        print(f"Creating availability timeseries for consumption {consumption.name}")
        ga = Availability(consumption.name, DotDict({"db": {consumption.name: consumption.__dict__}}))
        ga.set_scenario(self.station_distribution)
        ga.run()
        print(f"Availability timeseries created {ga.name}")
        return ga

    def create_demand_timeseries(self, availability: Availability):
        print(f"Creating demand timeseries for availability {availability.name}")
        ged = Charging(availability.name)
        ged.load_scenario(DotDict({"db": {availability.name: availability.__dict__}}))
        ged.set_sub_scenario("immediate")
        ged.run()
        print(f"Demand timeseries created {ged.name}")
        return ged

    def get_loads_at_time(self, time=None, time_hours=None):
        if not time:
            time = self.start_date + timedelta(hours=time_hours)
        row = self.demand_df.xs('charge_grid', level=1, axis=1).asof(time)
        return row.values * 1000  # convert to W

    def get_stored_power(self):
        socs = self.demand_df.xs('actual_soc', level=1, axis=1)
        battery_capacities = np.array([p.car_model.parameters["battery_cap"] for p in self.profiles]) * 1000
        stored = pd.concat([(socs * battery_capacities)], axis=1, keys=['stored_power']).swaplevel(0, 1, 1)
        return stored.join(pd.concat([socs], axis=1, keys=["soc"]).swaplevel(0, 1, 1))

    def get_stored_power_at_time(self, time=None, time_hours=None):
        if not time:
            time = self.start_date + timedelta(hours=time_hours)
        return self.get_stored_power().asof(time)

    def get_locations_at_time(self, time=None, time_hours=None):
        if not time:
            time = self.start_date + timedelta(hours=time_hours)
        row = self.demand_df.xs('charging_point', level=1, axis=1).asof(time)
        return row.values  # convert to W

    def draw_figures(self):
        fig = make_subplots(rows=1, cols=1,
                            specs=[[{}]])
        fig.update_layout(title_text="EV Locations")

        # EV Locations
        states = self.consumption_df.xs('state', level=1, axis=1).apply(lambda x: collections.Counter(x), axis=1,
                                                                        result_type="expand")
        states = states[(states.index >= self.start_date) & (states.index <= self.end_date)]
        fig.add_traces([
            {
                "type": "scatter",
                "x": states.index,
                "y": states[column],
                "name": f"{column}",
                "stackgroup": "location",
                "line": {"width": 1}
            }
            for column in states.columns
        ], rows=1, cols=1)

        fig.update_xaxes(title_text="", row=1, col=1, tickformat="%H:%M")
        fig.update_yaxes(title_text="EV Locations", row=1, col=1)
        layout(fig, 1200, 400)
        fig.write_html("ev_locations.html")
        fig.write_image("ev_locations.png")
        print(f"Wrote EV locations figure to ev_locations.html and ev_locations.png")

        fig = make_subplots(rows=1, cols=1,
                            specs=[[{"secondary_y": True}]])
        fig.update_layout(title_text="EV Driving Load")

        # EV Driving Loads
        driving_loads = self.consumption_df.xs('average power in W', level=1, axis=1).apply(lambda x: x, axis=1,
                                                                                            result_type="expand")

        driving_loads = driving_loads[(driving_loads.index >= self.start_date) & (driving_loads.index <= self.end_date)]

        driving_load_total = driving_loads.sum(axis=1)
        fig.add_trace(
            {
                "type": "scatter",
                "x": driving_load_total.index,
                "y": driving_load_total,
                "name": f"Total driving load",
                # "showlegend": False,
                # "line": {"color": k}
            }, row=1, col=1)
        driving_energy_total = driving_load_total.cumsum()
        fig.add_trace(
            {
                "type": "scatter",
                "x": driving_energy_total.index,
                "y": driving_energy_total,
                "name": f"Cumulative driving energy use",
                # "showlegend": False,
                # "line": {"color": k}
            }, row=1, col=1, secondary_y=True)

        fig.update_xaxes(title_text="", row=1, col=1, tickformat="%H:%M")
        fig.update_yaxes(title_text="EV Driving Load (W)", row=1, col=1)
        fig.update_yaxes(title_text="EV Energy Used (J)", row=1, col=1, secondary_y=True)
        layout(fig, 1200, 400)
        fig.write_html("ev_driving_loads.html")
        fig.write_image("ev_driving_loads.png")
        print(f"Saved EV driving loads figure to ev_driving_loads.html, ev_driving_loads.png")


def total_between(ss, start_time: datetime, end_time: datetime):
    t = start_time
    energy = 0.0
    while t < end_time:
        future_indices = ss.loc[ss.index > t].index
        next_index = future_indices[0] if len(future_indices) else end_time
        next_t = min(next_index, end_time)
        delta = (next_t - t).total_seconds()
        energy += delta * ss.asof(t)
        t = next_t
    return energy


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='python3 ev_profiles.py',
        description='Generate collections of EV profiles using emobpy for use by the EV federate')

    parser.add_argument("-n", "--num_ev", type=int, default=30)

    date_type = lambda s: datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
    parser.add_argument("-s", "--start_date", type=date_type, default=datetime(2013, 7, 1, 0, 0, 0))
    end_time_group = parser.add_mutually_exclusive_group()
    end_time_group.add_argument("-e", "--end_date", type=date_type)
    end_time_group.add_argument("-t", "--total_hours", type=int, default=192)

    command_group = parser.add_mutually_exclusive_group()
    command_group.add_argument("-g", "--generate_profiles", help="Generate profiles", action="store_true")
    command_group.add_argument("-f", "--show_figures", default=192, help="Load saved profiles and show figures",
                               action="store_true")

    args = parser.parse_args()
    end_date = args.end_date if args.end_date else args.start_date + timedelta(hours=args.total_hours)

    ev_profiles = EVProfiles(args.start_date, end_date, 0.125, args.num_ev, "emobpy_data/profiles")
    if args.generate_profiles:
        ev_profiles.run(pool_size=1)
    elif args.show_figures:
        ev_profiles.load_from_saved()
        ev_profiles.draw_figures()

    avg_powers = sum(p.consumption.timeseries["average power in W"] for p in ev_profiles.profiles)
    avg_powers = avg_powers[(avg_powers.index >= args.start_date) & (avg_powers.index <= end_date)]

    rpt = avg_powers[:-1].repeat(2).set_axis(avg_powers.index.repeat(2)[1:-1])
    idx = pd.date_range(args.start_date, end_date, freq=f'300S')
    driving_power_totals = pd.Series([total_between(rpt, s, s + timedelta(seconds=300)) / 300 for s in idx], index=idx)
    pickle.dump(driving_power_totals, open("driving_power.pkl", "wb"))
