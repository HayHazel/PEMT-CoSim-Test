# file: launch substation.py
"""
Function:
        start running substation federate (main federate) as well as other federates
last update time: 2022-6-15
modified by Yuanliang Li
"""
import pickle
from datetime import datetime
from datetime import timedelta

import helics

from PET_Prosumer import House, GridSupply  # import user-defined my_hvac class for hvac controllers
from federate_helper import FederateHelper
from market import ContinuousDoubleAuction
from recording import SubstationRecorder


class PETFederate:
    def __init__(self, scenario, helics_config: str, start_time: datetime, hour_stop: int):
        print("initialising PETFederate", flush=True)
        self.start_time = start_time
        self.current_time = start_time
        self.hour_stop = hour_stop
        self.stop_seconds = int(hour_stop * 3600)  # co-simulation stop time in seconds

        self.draw_figure = True  # draw figures during the simulation
        # self.fh = FederateHelper(configfile)  # initialize the federate helper
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

        self.recorder = SubstationRecorder(self.grid_supply, self.houses, self.auction)

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

    def run(self):
        while (
                time_granted := self.helics_federate.request_time(
                    min([self.next_update_time, self.next_market_time, self.stop_seconds]))) < self.stop_seconds:
            self.current_time = self.start_time + timedelta(seconds=time_granted)  # this is the actual time
            print(f"substation federate granted time {time_granted} = {self.current_time}")

            """ 2. houses update state/measurements for all devices, 
                   update schedule and determine the power needed for hvac,
                   make power predictions for solar,
                   make power predictions for house load"""
            if time_granted >= self.next_update_time or True:
                for house_name, house in self.houses.items():
                    house.update_measurements(self.current_time)  # update measurements for all devices
                    house.hvac.change_basepoint(self.current_time.hour + self.current_time.minute / 60, self.current_time.weekday())  # update schedule
                    house.hvac.determine_power_needed(
                        self.grid_supply.weather_temp)  # hvac determines if power is needed based on current state
                self.grid_supply.update_load()  # get the VPP load
                self.recorder.record_houses(self.current_time)
                self.recorder.record_grid(self.current_time)
                self.next_update_time += self.update_period

            """ 5. houses formulate and send their bids"""
            if time_granted >= self.next_market_time:
                # auction.clear_bids()  # auction remove all previous records, re-initialize
                # print(
                #     f"EVs @ {[(i, house.ev.location, house.ev.soc, house.ev.load_range) for i, house in enumerate(self.houses.values()) if house.ev is not None]}")
                # print(
                #     f"LOADs @ {[(i, house.unresponsive_load, house.hvac.hvac_load, house.ev.measured_load if house.ev else 0) for i, house in enumerate(self.houses.values())]}")
                # print(
                #     f"HVAC LOADS SUM {sum(house.hvac.hvac_load for house in self.houses.values())} @ {[(i, house.hvac.hvac_load) for i, house in enumerate(self.houses.values())]}")
                # print("AUCTION HISTORY BEFORE BIDS")
                # print(self.auction.history)
                bids = [bid for house in self.houses.values() for bid in house.formulate_bids()] + [
                    self.grid_supply.formulate_bid()]
                self.auction.collect_bids(bids)
                self.auction.update_lmp()  # get local marginal price (LMP) from the bulk power grid
                self.auction.update_refload()  # get distribution load from gridlabd
                market_response = self.auction.clear_market(self.current_time)
                for trader, transactions in market_response.items():
                    if trader == self.grid_supply.name:
                        self.grid_supply.post_market_control(transactions)
                    else:
                        self.houses[trader].post_market_control(transactions)

                self.recorder.record_auction(self.current_time)
                self.next_market_time += self.market_period

            """ 9. visualize some results during the simulation"""
            if self.draw_figure and time_granted >= self.next_figure_time:
                self.recorder.figure()
                self.next_figure_time += self.fig_update_period
                self.recorder.save(f"metrics/{scenario.name}.pkl")
        self.recorder.save(f"metrics/{scenario.name}.pkl")
        print('writing metrics', flush=True)
        helics.helicsFederateDestroy(self.helics_federate)
        print(f"federate {self.helics_federate.name} has been destroyed")


with open("../scenario.pkl", "rb") as f:
    scenario = pickle.load(f)

fed = PETFederate(
    scenario,
    'TE_Challenge_HELICS_substation.json',
    datetime.strptime('2013-07-01 00:00:00 -0800', '%Y-%m-%d %H:%M:%S %z'),
    192
)

fed.initialise()
fed.run()
