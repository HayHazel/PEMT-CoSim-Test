import json
import pickle
import sys
from collections import namedtuple
from datetime import datetime, timedelta

import helics
import numpy as np
import pandas
from helics import HelicsFederate

from pet_ev import V2GEV
from ev_profiles import EVProfiles, EVProfile
sys.path.append("../")
from scenario import PETScenario

EVPublications = namedtuple("EVPublications", "location load")


class EVFederate:
    def __init__(self, scenario: PETScenario):
        self.scenario = scenario
        self.fed_name = None
        self.time_period_hours = 0.125
        self.time_period_seconds = self.time_period_hours * 3600
        self.num_evs = scenario.num_ev
        self.helics_fed: HelicsFederate = None
        self.start_time = scenario.start_time
        self.current_time = self.start_time
        self.end_time = scenario.end_time
        # self.hour_stop = (self.end_time - self.start_time).total_seconds() / 3600
        self.market_period = 300

        self.ev_profiles = EVProfiles(self.start_time, self.end_time, self.time_period_hours, self.num_evs,
                                      "emobpy_data/profiles").load_from_saved()

        self.evs: list[V2GEV] = []

        self.stop_seconds = (self.end_time - self.start_time).total_seconds() * 3600  # co-simulation stop time in seconds
        self.enabled = True

        self.prev_state_strings = [""] * self.num_evs

    def create_federate(self):
        print(f"Creating EV federate")
        fed_json = {
            "name": "ev1",
            "uninterruptible": False,
            "publications": [
                p for i in range(self.num_evs) for p in [
                    {
                        "key": f"H{i}_ev#location",
                        "type": "string",
                        "global": False
                    },
                    {
                        "key": f"H{i}_ev#stored_energy",
                        "type": "double",
                        "global": False
                    },
                    {
                        "key": f"H{i}_ev#soc",
                        "type": "double",
                        "global": False
                    },
                    {
                        "key": f"H{i}_ev#charging_load",
                        "type": "complex",
                        "global": False
                    },
                    {
                        "key": f"H{i}_ev#max_charging_load",
                        "type": "double",
                        "global": False
                    },
                    {
                        "key": f"H{i}_ev#min_charging_load",
                        "type": "double",
                        "global": False
                    }
                ]
            ],
            "subscriptions": [
                {
                    "key": f"pet1/H{i}_ev#charge_rate",
                    "type": "double"
                } for i in range(self.num_evs)
            ]
        }
        with open("ev_helics_config.json", "w") as config_file:
            json.dump(fed_json, config_file, indent=4)

        self.helics_fed = helics.helicsCreateValueFederateFromConfig("ev_helics_config.json")
        self.fed_name = self.helics_fed.name
        print(f"EV federate {self.fed_name} created", flush=True)
        initial_socs = np.linspace(0.4, 0.8, self.num_evs)
        self.evs = [
            V2GEV(self.helics_fed, f"H{i}_ev", self.current_time, profile.consumption, profile.car_model,
                  scenario.workplace_charge_capacity,
                  initial_soc=initial_socs[i])
            for i, profile in enumerate(self.ev_profiles.profiles)
        ]

        print("EV federate publications registered")

    def state_summary(self):
        data = pandas.DataFrame(
            [
                [ev.location, ev.stored_energy, ev.charging_load, ev.stored_energy / ev.battery_capacity,
                 ev.time_to_full_charge]
                for ev in self.evs if ev.charging_load > 0.0
            ],
            columns=["location", "stored_energy", "charge_rate", "soc", "time_to_full_charge"])

        return f"{self.current_time}: {len(data)} EVs charging, next battery full in {min(data['time_to_full_charge']) if len(data) else '<inf>'}s"

    def save_data(self):
        data = pandas.concat(
            [pandas.DataFrame(ev.history, columns=["time", "location", "stored_energy", "charge_rate", "soc",
                                                   "workplace_charge_rate"]) for ev in
             self.evs], axis=1,
            keys=range(self.num_evs))
        pickle.dump(data, open(f"{scenario.name}_ev_history.pkl", "wb"))

    def market_update(self, new_time: datetime, next_time_to_request: float):
        print(f"market iter 1, granted {new_time}")
        for ev in self.evs:
            ev.publish_capacity()

        while res := self.request_time(next_time_to_request, True):
            time_granted_seconds, iteration_result = res
            new_time = self.start_time + timedelta(seconds=time_granted_seconds)
            print(f"market iter 2, granted {time_granted_seconds} = {new_time} | {iteration_result}")
            for ev in self.evs:
                ev.update_charge_rate()

    def update_ev_states(self, new_time):
        for ev in self.evs:
            ev.update_state(new_time)

        new_state_strings = [
            f'{i}: {ev.location}, SOC {ev.stored_energy / ev.battery_capacity:3f}, CL {ev.charging_load:3f}, desired {ev.desired_charge_load}'
            for i, ev in enumerate(self.evs)]
        diff_state_strings = [s for i, s in enumerate(new_state_strings) if self.prev_state_strings[i] != s]
        self.prev_state_strings = new_state_strings
        print(
            f"{self.current_time}: EVs updated state: changed {diff_state_strings}")

    def request_time(self, time_to_request, needs_iteration):
        time_granted_seconds, iter_res = self.helics_fed.request_time_iterative(time_to_request,
                                                                                helics.HELICS_ITERATION_REQUEST_ITERATE_IF_NEEDED
                                                                                if needs_iteration
                                                                                else helics.HELICS_ITERATION_REQUEST_NO_ITERATION)
        print(
            f"requested time {time_to_request} with needs_iter={needs_iteration}, got {time_granted_seconds}, {iter_res} = {self.start_time + timedelta(seconds=time_granted_seconds)}")
        return time_granted_seconds, iter_res

    def run(self):
        print("EV federate to enter initializing mode", flush=True)
        self.helics_fed.enter_initializing_mode()
        print("EV federate entered initializing mode", flush=True)
        for ev in self.evs:
            ev.publish_state()
            ev.publish_capacity()
        print("published initial states", list(enumerate([ev.location for ev in self.evs])))

        print("EV federate to enter execution mode")
        self.helics_fed.enter_executing_mode()
        print("EV federate entered execution mode")
        if self.num_evs == 0:
            print("EV federate has 0 EVs, finishing early")
            return

        next_premarket_time = 0
        next_market_time = 0
        next_full_charge = 0
        next_location_change = 0
        next_save_time = 0
        time_to_request = 0
        time_granted_seconds = 0
        while time_granted_seconds < self.stop_seconds:
            time_granted_seconds = self.helics_fed.request_time(time_to_request)

            new_time = self.start_time + timedelta(seconds=time_granted_seconds)
            print(f"\nREQUESTED time {time_to_request}, GRANTED {time_granted_seconds} = {new_time}")

            self.update_ev_states(new_time)
            self.current_time = new_time
            print(self.state_summary(), flush=True)

            if time_granted_seconds >= next_premarket_time:
                # self.current_time = self.start_time + timedelta(seconds=next_market_time)
                # print(f"updating to premarket states for {self.current_time}")
                for ev in self.evs:
                    ev.update_state(self.start_time + timedelta(seconds=next_market_time))
                    ev.publish_capacity()
                caps = [ev.charging_load_range for ev in self.evs]
                # print(f"published premarket capacities {caps} for {self.current_time}")
                # self.current_time = self.start_time + timedelta(seconds=time_granted_seconds)

            # if time_granted_seconds >= next_market_time:
            for ev in self.evs:
                ev.update_charge_rate()
            print(f"published charge rates for {self.current_time}")

            if time_granted_seconds >= next_save_time:
                print(f"writing data @ {self.current_time}")
                self.save_data()

            next_full_charge = min([ev.time_to_full_charge for ev in self.evs]) + time_granted_seconds
            next_location_change = min([ev.next_location_change()[0] for ev in self.evs]) + time_granted_seconds
            d = 0.001
            next_premarket_time = ((time_granted_seconds + d) // self.market_period + 1) * self.market_period - d
            next_market_time = (time_granted_seconds // self.market_period + 1) * self.market_period
            next_save_time = (time_granted_seconds // self.scenario.figure_period + 1) * self.scenario.figure_period
            time_to_request = min(next_location_change, next_full_charge, self.stop_seconds, next_premarket_time,
                                  next_market_time, next_save_time)

        self.save_data()
        print("EV federate finished + saved", flush=True)
        # self.publish_locations()


with open("../scenario.pkl", "rb") as f:
    scenario: PETScenario = pickle.load(f)

federate = EVFederate(scenario)
federate.create_federate()
federate.enabled = True
federate.run()
federate.helics_fed.finalize()
