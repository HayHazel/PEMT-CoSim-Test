import pickle
import sys
from datetime import datetime, timezone
from datetime import timedelta

import helics

from PET_Prosumer import House, GridSupply
from market import ContinuousDoubleAuction
from recording import SubstationRecorder

sys.path.append("../")
from scenario import PETScenario


class PETFederate:
    def __init__(self, scenario, helics_config: str):
        print("initialising PETFederate", flush=True)
        # localise the provided start times to the simulation area
        self.start_time = scenario.start_time.replace(tzinfo=timezone(timedelta(hours=-8)))
        self.current_time = self.start_time
        self.end_time = scenario.end_time.replace(tzinfo=timezone(timedelta(hours=-8)))
        self.stop_seconds = (self.end_time - self.start_time).total_seconds()  # co-simulation stop time in seconds

        self.draw_figure = True  # draw figures during the simulation
        self.helics_federate = helics.helicsCreateValueFederateFromConfig(helics_config)

        self.auction = ContinuousDoubleAuction(self.helics_federate, self.current_time)
        self.grid_supply = GridSupply(self.helics_federate, self.auction, scenario.grid_power_cap)
        self.houses = {
            f"H{house_id}": House(self.helics_federate, house_id, scenario,
                                  scenario.hvac_configs[house_id], house_id < scenario.num_pv,
                                  house_id < scenario.num_ev, self.auction)
            for house_id in range(scenario.num_houses)
        }
        self.update_period = 15  # state update period (15 seconds)
        self.market_period = 300  # market period (300 seconds)
        self.fig_update_period = scenario.figure_period  # figure update time period

        self.next_update_time = 0  # the next time to update the state
        self.next_market_time = 0
        self.next_figure_time = 0  # the next time to update figures

        self.time_granted = 0

        self.recorder = SubstationRecorder(self.grid_supply, self.houses, self.auction, f"metrics/{scenario.name}")

    def initialise(self):
        print("Substation federate to enter initializing mode", flush=True)
        self.helics_federate.enter_initializing_mode()
        print("Substation federate entered initializing mode", flush=True)

        for house_name, house in self.houses.items():  # key: house name, info: information of the house, including names of PV, battery ...
            house.set_meter_mode()  # set meter mode
            house.hvac.set_on(False)  # at the beginning of the simulation, turn off all HVACs
            if house.ev is not None:
                house.ev.set_desired_charge_rate(0)
        print("Substation federate to enter executing mode")
        self.helics_federate.enter_executing_mode()
        print("Substation federate entered executing mode")

    def update_states(self):
        for house_name, house in self.houses.items():
            house.update_measurements(self.current_time)  # update measurements for all devices
            house.hvac.change_basepoint(self.current_time.hour + self.current_time.minute / 60)  # update schedule
            house.hvac.determine_power_needed(
                self.grid_supply.weather_temp)  # hvac determines if power is needed based on current state
        self.grid_supply.update_load()  # get the VPP load

    def run(self):
        time_granted_seconds = 0
        while time_granted_seconds < self.stop_seconds:
            time_to_request = max(0, min([self.next_update_time, self.next_market_time, self.stop_seconds]))
            time_granted_seconds = self.helics_federate.request_time(time_to_request)

            """ 0. visualize some results during the simulation"""
            if self.draw_figure and time_granted_seconds >= self.next_figure_time:
                self.recorder.save_progress_figure(False)
                self.recorder.save()

            self.current_time = self.start_time + timedelta(seconds=time_granted_seconds)  # this is the actual time

            print(f"REQUESTED time {time_to_request}, GRANTED {time_granted_seconds} = {self.current_time}")

            """ 1. houses update state/measurements for all devices, 
                   update schedule and determine the power needed for hvac,
                   make power predictions for solar,
                   make power predictions for house load,
                   update lmp"""
            if time_granted_seconds >= self.next_update_time or True:
                self.update_states()
                self.auction.update_lmp(self.current_time)

            """ 2. receive capacity from EVs, formulate bids, set loads"""
            if time_granted_seconds >= self.next_market_time:
                print(f"Market round @  {self.current_time}")
                self.auction.update_lmp(self.current_time)  # get local marginal price (LMP) from the bulk power grid
                self.auction.update_stats()
                bids = [bid for house in self.houses.values() for bid in house.formulate_bids()] + [
                    self.grid_supply.formulate_bid()]
                self.auction.collect_bids(bids)
                self.auction.update_refload()  # get distribution load from gridlabd
                market_response = self.auction.clear_market(self.current_time)
                for trader, transactions in market_response.items():
                    if trader == self.grid_supply.name:
                        self.grid_supply.post_market_control(transactions)
                    else:
                        self.houses[trader].post_market_control(transactions)
                self.recorder.record_auction(self.current_time)

            """ 3. record data"""
            self.recorder.record_houses(self.current_time)
            self.recorder.record_grid(self.current_time)

            self.next_market_time = (time_granted_seconds // self.market_period + 1) * self.market_period
            self.next_figure_time = (time_granted_seconds // self.fig_update_period + 1) * self.fig_update_period
            self.next_update_time = (time_granted_seconds // self.update_period + 1) * self.update_period

        self.recorder.save()
        print('writing metrics', flush=True)
        helics.helicsFederateDestroy(self.helics_federate)
        print(f"federate {self.helics_federate.name} has been destroyed")


with open("../scenario.pkl", "rb") as f:
    scenario: PETScenario = pickle.load(f)

fed = PETFederate(
    scenario,
    'substation_helics_config.json'
)

fed.initialise()
fed.run()
