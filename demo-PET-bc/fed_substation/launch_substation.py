# file: launch substation.py
"""
Function:
        start running substation federate (main federate) as well as other federates
last update time: 2022-12-20
modified by Ye Chen & Peilin Wu
"""

import sys
sys.path.append('..')
# this is necessary since running this file is actually opening a new process
# where my_tesp_support_api package is not inside the path list
import time
import os
import json
import helics
import random
import psutil
import subprocess
from PET_Prosumer import HOUSE, VPP  # import user-defined my_hvac class for hvac controllers
from env import BIDING_ENV
from ddpg import DDPG
from datetime import datetime
from datetime import timedelta
from my_auction import AUCTION  # import user-defined my_auction class for market
import matplotlib.pyplot as plt
import my_tesp_support_api.helpers as helpers
from federate_helper import FEDERATE_HELPER, CURVES_TO_PLOT
import re
import sys

"""============================ Helper function ============================"""
def application_caller(application, js_application_path, args):
    try:
        # Run the command and capture the output
        print('node '+application +str(args))
        output = subprocess.check_output(['node', js_application_path + application]+args)
    except subprocess.CalledProcessError as e:
        # The command returned an error
        print(f'Error: {e}')
    else:
        # Decode the output from the subprocess
        s = output.decode('utf-8')
        return s

"""================================Blockchain check====================================="""


# fabric javascript application path
js_application_path = '../fabric_samples/double-auction/application-javascript/'
# to make sure whether the blockchain is running
res = application_caller('queryAuction.js', js_application_path, args=['org1', 'auctioneer', '000'])
if '"closed": false' in res:
    print('fabric system is runnng!')
else:
    sys.exit("fabric system is down, please use sudo bash reset.sh & sudo bash start.sh, "
             "their folder is ../../fabric-test/double-auction/application-javascript/test/")


"""================================Declare something====================================="""
data_path = './data/exp(utility-500)/'
if not os.path.exists(data_path):
    os.makedirs(data_path)
configfile = 'TE_Challenge_agent_dict.json'
helicsConfig = 'TE_Challenge_HELICS_substation.json'
metrics_root = 'TE_ChallengeH'
hour_stop = 3  # simulation duration (default 24 hours) in blockchain
hour_stop_seconds = hour_stop * 3600
hasMarket = True  # have market or not
vppEnable = False  # have Vpp coordinator or not
drawFigure = False  # draw figures during the simulation
drawFigure2 = False
has_demand_response = False
has_RL = False
fh = FEDERATE_HELPER(configfile, helicsConfig, metrics_root, hour_stop)  # initialize the federate helper

"""=============================Start The Co-simulation==================================="""
fh.cosimulation_start()  # launch the broker; launch other federates; the substation federate enters executing mode

"""============================Substation Initialization=================================="""
print('##,tnow,tclear,ClearType,ClearQ,ClearP,BuyCount,BuyUnresp,BuyResp,SellCount,SellUnresp,SellResp,'
      'MargQ,MargFrac,LMP,RefLoad,ConSurplus,AveConSurplus,SupplierSurplus,UnrespSupplierSurplus',
    flush=True)

# initialize a user-defined Vpp coordinator object
vpp_name = fh.vpp_name_list[0]  # select the first VPP
vpp = VPP(vpp_name, vppEnable)
vpp.get_helics_subspubs(fh.get_agent_pubssubs(vpp.name, 'VPP'))

# initialize a user-defined auction object
auction = AUCTION(fh.market_row, fh.market_key)
auction.get_helics_subspubs(fh.get_agent_pubssubs(auction.name, 'auction'))
auction.initAuction()

# initialize House objects
houses = {}
seed = 1
for key, info in fh.housesInfo_dict.items():  # key: house name, info: information of the house, including names of PV, battery ...
    houses[key] = HOUSE(key, info, fh.agents_dict, auction, seed)  # initialize a house object
    houses[key].get_helics_subspubs(
        fh.get_agent_pubssubs(key, 'house', info))  # get subscriptions and publications for house meters
    houses[key].set_meter_mode()  # set meter mode
    houses[key].get_cleared_price(auction.clearing_price)
    houses[key].hvac.turn_OFF()  # at the beginning of the simulation, turn off all HVACs
    seed += 1
last_house_name = key

# initialize RL agent for houses
if has_RL:
    for key, house in houses.items():
        house.rl_env = BIDING_ENV(len(houses), key, house.hvac.price_cap, hour_stop_seconds, 'seller-buyer')
        if house.rl_env.has_seller_agent:
            house.rl_agent_seller = DDPG(house.rl_env)
        if house.rl_env.has_buyer_agent:
            house.rl_agent_buyer = DDPG(house.rl_env)

# initialize DATA_TO_PLOT class to visualize data in the simulation
num_houses = len(houses)
curves = CURVES_TO_PLOT(num_houses)
if drawFigure:
    fig, (ax1, ax2, ax3, ax4, ax5, ax6) = plt.subplots(6)
    fig, ax7 = plt.subplots(1)
if drawFigure2:
   
    fig, ax7 = plt.subplots(1)
# initialize time parameters
StopTime = int(hour_stop * 3600)  # co-simulation stop time in seconds
#StopTime = 1797

StartTime = '2013-07-01 00:00:00 -0800'  # co-simulation start time
dt_now = datetime.strptime(StartTime, '%Y-%m-%d %H:%M:%S %z')

dt = fh.dt  # HELCIS period (1 seconds)
update_period = houses[last_house_name].hvac.update_period  # state update period (15 seconds)
control_period = houses[last_house_name].hvac.update_period
request_period = houses[last_house_name].hvac.request_period  # local controller samples energy packet request period
market_period = auction.period  # market period (300 seconds)
adjust_period = market_period  # market response period (300 seconds)
fig_update_period = market_period  # figure update time period
tnext_update = dt  # the next time to update the state
tnext_control = control_period
tnext_request = dt  # the next time to request
tnext_lmp = market_period - 3 * dt
tnext_bid = market_period - 2 * dt  # the next time controllers calculate their final bids
tnext_agg = market_period - 2 * dt  # the next time auction calculates and publishes aggregate bid
tnext_clear = market_period  # the next time clear the market
tnext_adjust = market_period  # the next time controllers adjust control parameters/setpoints based on their bid and clearing price 
tnext_fig_update = market_period + dt  # the next time to update figures

time_granted = 0
time_last = 0

"""============================Register House Accounts on Block Chain=================================="""

res_accounts = application_caller('queryAccounts.js', js_application_path, ['org1', 'auctioneer'])
registered_accounts_num = int(re.search(r"<Buffer ([0-9A-Fa-f]+)>", res_accounts).group(1), 16) # to compute the number of accounts.

if registered_accounts_num != 32:
    for index, house in enumerate(dict(list(houses.items())).items()):
        org = 'org1'
        print('I: ', house[0])
        res_user = application_caller('registerEnrollUser.js', js_application_path, [org, house[0]])
        print(res_user)
        res_account = application_caller('registerAccount.js', js_application_path, [org, house[0], str(1000000)])
        print(res_account)
# need to register UNRESPONSE SELLER & UNRESPONSE BUYER
res_user = application_caller('registerEnrollUser.js', js_application_path, ['org1', 'UNRESPONSE_BUYER'])
print(res_user)
res_account = application_caller('registerAccount.js', js_application_path, ['org1', 'UNRESPONSE_BUYER', str(1000000)])
print(res_account)
res_user = application_caller('registerEnrollUser.js', js_application_path, ['org1', 'UNRESPONSE_SELLER'])
print(res_user)
res_account = application_caller('registerAccount.js', js_application_path, ['org1', 'UNRESPONSE_SELLER', str(1000000)])
print(res_account)
"""============================Substation Loop=================================="""

while (time_granted < StopTime):
    # A sign of successful energy injection
    flag=False
    """ 1. step the co-simulation time """
    nextHELICSTime = int(
        min([tnext_update, tnext_request, tnext_lmp, tnext_bid, tnext_agg, tnext_clear, tnext_adjust, StopTime]))
    time_granted = int(helics.helicsFederateRequestTime(fh.hFed, nextHELICSTime))
    time_delta = time_granted - time_last
    time_last = time_granted
    hour_of_day = 24.0 * ((float(time_granted) / 86400.0) % 1.0)
    dt_now = dt_now + timedelta(seconds=time_delta)  # this is the actual time
    day_of_week = dt_now.weekday()  # get the day of week
    hour_of_day = dt_now.hour  # get the hour of the day
    """ 2. houses update state/measurements for all devices, 
         update schedule and determine the power needed for hvac,
         make power predictions for solar,
         make power predictions for house load"""
    
    if time_granted >= tnext_update:
        
        for key, house in houses.items():
            house.update_time(time_granted)  # update time for all elements of the house
            house.update_measurements()  # update measurements for all devices
            #Calculate the power of buyers participating in this auction
            if house.flag ==2 :
                house.smart_meter2(time_granted,js_application_path)
                if house.success == True:
                   flag = True
                else:
                   flag = False
            house.hvac.change_basepoint(hour_of_day, day_of_week)  # update schedule
            house.hvac.determine_power_needed()  # hvac determines if power is needed based on current state
            house.predict_solar_power()  # predict the solar power generation
            house.predict_house_load()  # predict the house load 
        number = tnext_bid
        if(time_granted > tnext_bid-1):
            #print('this is right ' + str(time_granted)) 
            if(flag == True):
                print('prefect, this auction is right!!!! next auction is begin  ' + ' at '+str(time_granted)) 
                res = application_caller('withdraw.js', js_application_path, ['org1', 'F0_house_A1', '000'])
                print(res)
                for key, house in houses.items():
                     if house.flag ==2 :
                          #You can query  house account after this transaction
                          print('query ' + house.name+ ' wallet at  '+str(time_granted)) 
                          res = application_caller('queryUserAccount.js', js_application_path, ['org1', 'F0_house_A1', house.name])
                          print(res)
                          house.flag = 1
            
        vpp.get_vpp_load()  # get the VPP load
        curves.record_state_statistics(time_granted, houses, auction, vpp)  # record something
        tnext_update += update_period

    """ 3. houses launch basic real-time control actions (not post-market control)
      including the control for battery  """
    if time_granted >= tnext_control:
        for key, house in houses.items():
            if house.hasBatt:
                house.battery.auto_control()  # real-time basic control of battery to track the HVAC load
            # house.hvac.auto_control()
        tnext_control += control_period

    """ 4. market gets the local marginal price (LMP) from the bulk power grid,"""
    if time_granted >= tnext_lmp:
        auction.get_lmp()  # get local marginal price (LMP) from the bulk power grid
        auction.get_refload()  # get distribution load from gridlabd
        for key, house in houses.items():
            house.get_lmp_from_market(auction.lmp)  # houses get LMP from the market
        tnext_lmp += market_period

    """ 5. iterative double-auction"""
    #tnext_bid = market_period - 2 * dt ,means 298 += 300
    if time_granted >= tnext_bid:
        time_key = str(int(tnext_bid))
        fh.prosumer_metrics[time_key] = {}
       
        for key, house in houses.items():
            house.get_quantity_choice()
        # start iterative
        for i in range(1):
            auction.clear_bids()  # auction remove all previous records, re-initialize
            end_flag = True
            for key, house in houses.items():
                house.bid = house.formulate_bid_iterative(
                    i)  # bid is [bid_price, quantity, hvac.power_needed, role, unres_kw, name]
                auction.collect_bid(house.bid)
                # to transfer decimals bid quantity to int
                end_flag *= (not house.bid['updated'])
            auction.aggregate_bids()
            auction.clear_market(js_application_path, houses,time_granted)
            auction.surplusCalculation(tnext_clear, time_granted)
            auction.get_social_welfare()
            auction.aggregate_results_for_prosumers()
            auction_info = auction.publish_cleared_market_information()  # used to generate the observation for agent
            for key, house in houses.items():
                house.get_cleared_public_market_information(auction_info)
                house.get_result_from_market(auction.send_result_to_agent(house.name))
            if end_flag:
                break
        print("!!The cleared price is: ", auction_info['cleared-price'])
        # for test cleared price time
        print( '!!The cleared price at '+str(time_granted))
        for key, house in houses.items():
            fh.prosumer_metrics[time_key][house.name] = [house.bid['bid-price'], house.bid['bid-quantity'],
                                                         house.bid['hvac-needed'], house.bid['role'], \
                                                         house.bid['base-covered'], house.bid['bid-baseload'],
                                                         house.result['determination'],
                                                         house.result['dispatched-quantity']]
            house.calculate_reward()
            house.publish_meter_price()
            house.post_market_control2(auction_info)  # post-market control is needed)
        print(i)

        fh.auction_metrics[time_key] = {
            auction.name: [auction.clearing_price, auction.clearing_type, auction.consumerSurplus,
                           auction.averageConsumerSurplus, auction.supplierSurplus]}
        curves.record_auction_statistics(time_granted, houses, auction)
        tnext_bid += market_period

    """ 8. prosumer demand response (adjust control parameters/setpoints) """
    if time_granted >= tnext_adjust:
        if has_demand_response:
            for key, house in houses.items():
                house.demand_response()
        tnext_adjust += market_period

    """ 9. visualize some results during the simulation"""
    if drawFigure and time_granted >= tnext_fig_update:
        curves.update_curves(time_granted)
        ax1.cla()
        ax1.set_ylabel("System Load (kW)")
        # ax1.plot(curves.time_hour_curve, curves.curve_distri_load_p)
        ax1.plot(curves.time_hour_curve, curves.curve_vpp_load_p)
        if curves.curve_vpp_load_p[-1] < 0:
            a = 1
        ax1.plot(curves.time_hour_curve, curves.curve_system_PV)
        ax1.plot(curves.time_hour_curve, curves.curve_system_Batt)
        ax1.legend(['Total flow', 'Total PV', 'Total Battery'])

        ax2.cla()
        ax2.set_ylabel("House Load (kW)")
        ax2.plot(curves.time_hour_curve, curves.curve_house_load_max)
        ax2.plot(curves.time_hour_curve, curves.curve_house_load_mean)
        ax2.plot(curves.time_hour_curve, curves.curve_house_load_min)
        ax2.legend(['max', 'mean', 'min'])

        ax3.cla()
        ax3.set_ylabel("Temperature (degF)")
        ax3.plot(curves.time_hour_curve, curves.curve_temp_max)
        ax3.plot(curves.time_hour_curve, curves.curve_temp_mean)
        ax3.plot(curves.time_hour_curve, curves.curve_temp_min)
        ax3.plot(curves.time_hour_curve, curves.curve_basepoint_mean)
        ax3.plot(curves.time_hour_curve, curves.curve_setpoint_mean)
        ax3.legend(['max', 'mean', 'min', 'base-point', 'set-point'])

        ax4.cla()
        ax4.set_ylabel("Price ($/kwh)")
        ax4.plot(curves.time_hour_curve, curves.curve_cleared_price)
        ax4.plot(curves.time_hour_curve, curves.curve_LMP)
        ax4.legend(['cleared price', 'LMP'])

        ax5.cla()
        ax5.set_ylabel("Percentage")
        ax5.plot(curves.time_hour_curve, curves.curve_hvac_on_ratio)
        ax5.plot(curves.time_hour_curve, curves.curve_house_SoC_mean)
        ax5.plot(curves.time_hour_curve, curves.curve_buyer_ratio)
        ax5.plot(curves.time_hour_curve, curves.curve_seller_ratio)
        ax5.plot(curves.time_hour_curve, curves.curve_nontcp_ratio)
        ax5.legend(['HVAC-ON ratio', 'SoC mean', 'Buyer ratio', 'Seller ratio', 'None-participant ratio'])

        ax6.cla()
        ax6.set_xlabel("Time (h)")
        ax6.set_ylabel("Social Welfare ($)")
        ax6.plot(curves.time_hour_curve, curves.curve_social_welfare_seller_income)
        ax6.plot(curves.time_hour_curve, curves.curve_social_welfare_combined_surplus)
        ax6.legend(['Seller Income', 'Surplus'])

        plt.pause(0.01)
        tnext_fig_update += fig_update_period

"""============================ Finalize the metrics output ============================"""
curves.save_statistics(data_path)
print('writing metrics', flush=True)
auction_op = open(data_path + 'auction_' + metrics_root + '_metrics.json', 'w')
print(json.dumps(fh.auction_metrics), file=auction_op)
auction_op.close()
house_op = open(data_path + 'house_' + metrics_root + '_metrics.json', 'w')
print(json.dumps(fh.prosumer_metrics), file=house_op)
house_op.close()
fh.destroy_federate()  # destroy the federate
fh.show_resource_consumption()  # after simulation, print the resource consumption
plt.show()
# fh.kill_processes(True) # it is not suggested here because some other federates may not end their simulations, it will affect their output metrics
