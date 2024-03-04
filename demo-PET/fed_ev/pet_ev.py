from datetime import datetime
from enum import IntEnum

import helics
import numpy as np
from emobpy import ModelSpecs, Consumption
from helics import HelicsFederate


# PET EV controller
# uses mobility/grid-availability data from emobpy to simulate an EV responding to PET
# market conditions according to a strategy.
class V2GEV:
    def __init__(self, helics_fed: HelicsFederate, name: str, start_time: datetime, consumption: Consumption,
                 car_model: ModelSpecs, workplace_charge_capacity=7000, initial_soc=0.5, market_period=300):
        self.helics_fed = helics_fed
        self.name = name
        self.profile = consumption.timeseries
        self.location_changes = self.profile[(self.profile["state"].shift() != self.profile["state"])]
        self.market_period = market_period

        # parameters
        self.car_model = car_model
        self.max_home_discharge_rate = 5000
        self.max_home_charge_rate = 5000
        self.min_home_charge_rate = 2500
        self.battery_capacity = car_model.parameters["battery_cap"] * 1000 * 3600
        self.work_charge_capacity = workplace_charge_capacity
        self.charging_efficiency = car_model.parameters["battery_charging_eff"]
        self.discharging_efficiency = car_model.parameters["battery_discharging_eff"]
        self.charging_efficiencies = self.discharging_efficiency, self.charging_efficiency
        self.enable_movement = True
        self.enable_charging = True
        self.enable_discharging = True

        # state
        self.stored_energy = initial_soc * self.battery_capacity
        self.location = self.profile["state"].asof(start_time)
        self.desired_charge_load = 0.0
        self.charging_load = 0.0
        self.workplace_charge_rate = 0.0
        self.time_to_full_charge = float('inf')
        self.charging_load_range = 0.0, 0.0
        self.prev_time = start_time
        self.current_time = start_time
        self.history = []

        # HELICS publications and subscriptions
        self.pub_location = helics.helicsFederateGetPublication(self.helics_fed, f"{name}#location")
        self.pub_stored_energy = helics.helicsFederateGetPublication(self.helics_fed, f"{name}#stored_energy")
        self.pub_charging_load = helics.helicsFederateGetPublication(self.helics_fed, f"{name}#charging_load")
        self.pub_soc = helics.helicsFederateGetPublication(self.helics_fed, f"{name}#soc")

        self.pub_max_charging_load = helics.helicsFederateGetPublication(self.helics_fed, f"{name}#max_charging_load")
        self.pub_min_charging_load = helics.helicsFederateGetPublication(self.helics_fed, f"{name}#min_charging_load")

        self.sub_desired_charge_load = helics.helicsFederateGetSubscription(self.helics_fed, f"pet1/{name}#charge_rate")

    def driving_energy_between(self, start_time: datetime, end_time: datetime):
        if not self.enable_movement:
            return 0.0
        avg_power = self.profile["average power in W"]
        t = start_time
        energy = 0.0
        while t < end_time:
            future_indices = avg_power.loc[avg_power.index > t].index
            next_index = future_indices[0] if len(future_indices) else end_time
            next_t = min(next_index, end_time)
            delta = (next_t - t).total_seconds()
            energy += delta * avg_power.asof(t)
            t = next_t
        return energy

    def record_history(self):
        self.history.append([self.current_time, self.location, self.stored_energy, self.charging_load,
                             self.stored_energy / self.battery_capacity, self.workplace_charge_rate])

    def publish_state(self):
        self.pub_location.publish(self.location)
        self.pub_stored_energy.publish(self.stored_energy)
        self.pub_charging_load.publish(complex(self.charging_load, 0))
        self.pub_soc.publish(self.stored_energy / self.battery_capacity)

    def next_location_change(self):
        if not self.enable_movement:
            return float('inf'), None

        future_changes = self.location_changes[self.location_changes.index > self.current_time]
        if len(future_changes):
            return (future_changes.index[0] - self.current_time).total_seconds(), future_changes.iloc[0]["state"]
        else:
            return float('inf'), None

    def charge_rate_range(self):
        max_discharge = -self.max_home_discharge_rate
        soc = self.stored_energy / self.battery_capacity
        time_to_next_loc, next_loc = self.next_location_change()

        if self.location != "home":
            return 0.0, 0.0
        elif next_loc != "home" and time_to_next_loc < self.market_period:
            return 0.0, 0.0
        elif .9 <= soc:
            return max_discharge, 0
        elif .3 <= soc < .9:
            return max_discharge, self.max_home_charge_rate
        elif .2 <= soc < .3:
            return 0, self.max_home_charge_rate
        else:
            return self.min_home_charge_rate, self.max_home_charge_rate

    def grid_load_range(self):
        charge_rate = self.charge_rate_range()
        return list(map(lambda x: x / self.charging_efficiencies[x > 0], charge_rate))

    def update_charge_rate(self):
        self.desired_charge_load = self.sub_desired_charge_load.double
        home_charge_load_intended = self.desired_charge_load * (self.location == "home")

        charge_rate_cap = max(0, ((self.battery_capacity * 0.9999) - self.stored_energy) / self.market_period)
        charge_load_cap = charge_rate_cap * self.enable_charging / self.charging_efficiency

        discharge_rate_cap = max(0, (self.stored_energy - (self.battery_capacity * 0.0001)) / self.market_period)
        discharge_load_cap = discharge_rate_cap * self.enable_discharging * self.discharging_efficiency

        home_charge_load = np.clip(home_charge_load_intended, -discharge_load_cap, charge_load_cap)

        self.charging_load = home_charge_load
        self.pub_charging_load.publish(complex(self.charging_load, 0))

    def publish_capacity(self):
        self.charging_load_range = self.grid_load_range()
        self.pub_min_charging_load.publish(self.charging_load_range[0])
        self.pub_max_charging_load.publish(self.charging_load_range[1])

    def update_state(self, new_time: datetime):
        self.prev_time = self.current_time
        self.current_time = new_time

        time_delta = (self.current_time - self.prev_time).total_seconds()
        if time_delta == 0:
            return

        if self.sub_desired_charge_load.is_updated():
            self.update_charge_rate()

        # calculate energy used up to now
        driving_energy_used = self.driving_energy_between(self.prev_time, self.current_time)

        home_charge_rate = self.charging_load * self.charging_efficiencies[self.charging_load > 0]

        self.stored_energy += home_charge_rate * time_delta - driving_energy_used

        if 0.9999 < self.stored_energy / self.battery_capacity and self.stored_energy != self.battery_capacity:
            print(f"{self.name} reached full charge")
            self.stored_energy = self.battery_capacity

        self.time_to_full_charge = ((self.battery_capacity - self.stored_energy) / self.charging_load) \
            if self.charging_load > 0 and self.stored_energy < self.battery_capacity else float('inf')

        self.current_time = new_time
        self.location = self.profile["state"].asof(new_time) if self.enable_movement else "home"
        self.pub_location.publish(self.location)
        self.pub_stored_energy.publish(self.stored_energy)
        self.pub_soc.publish(self.stored_energy / self.battery_capacity)
