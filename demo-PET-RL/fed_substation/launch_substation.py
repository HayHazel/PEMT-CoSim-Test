# file: launch substation.py
"""
Function:
        start running substation federate (main federate) as well as other federates
last update time: 2022-6-15
modified by Yuanliang Li
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
import pickle
import subprocess
from PET_Prosumer import HOUSE, VPP        # import user-defined my_hvac class for hvac controllers
from env import BIDING_ENV
from ddpg import DDPG
from datetime import datetime
from datetime import timedelta
from my_auction import AUCTION  # import user-defined my_auction class for market
import matplotlib.pyplot as plt
import my_tesp_support_api.helpers as helpers
from federate_helper import FEDERATE_HELPER, CURVES_TO_PLOT



"""================================Declare something====================================="""
data_path = './data/exp(RL-test)/'
if not os.path.exists(data_path):
    os.makedirs(data_path)
configfile = 'TE_Challenge_agent_dict.json'
helicsConfig = 'TE_Challenge_HELICS_substation.json'
metrics_root = 'TE_ChallengeH'
hour_stop = 10#4*24  # simulation duration (default 48 hours)
hour_stop_seconds = hour_stop*3600
hasMarket = True # have market or not
vppEnable = False # have Vpp coordinator or not
drawFigure = True # draw figures during the simulation
has_demand_response = False
has_RL = True
fh = FEDERATE_HELPER(configfile, helicsConfig, metrics_root, hour_stop) # initialize the federate helper


"""=============================Start The Co-simulation==================================="""
fh.cosimulation_start() # launch the broker; launch other federates; the substation federate enters executing mode


"""============================Substation Initialization=================================="""
print ('##,tnow,tclear,ClearType,ClearQ,ClearP,BuyCount,BuyUnresp,BuyResp,SellCount,SellUnresp,SellResp,MargQ,MargFrac,LMP,RefLoad,ConSurplus,AveConSurplus,SupplierSurplus,UnrespSupplierSurplus', flush=True)

# initialize a user-defined Vpp coordinator object
vpp_name = fh.vpp_name_list[0] # select the first VPP
vpp = VPP(vpp_name,vppEnable)
vpp.get_helics_subspubs(fh.get_agent_pubssubs(vpp.name, 'VPP'))

# initialize a user-defined auction object
auction = AUCTION (fh.market_row, fh.market_key)
auction.get_helics_subspubs(fh.get_agent_pubssubs(auction.name, 'auction'))
auction.initAuction()


# initialize House objects
houses = {}
seed = 1
for key, info in fh.housesInfo_dict.items(): # key: house name, info: information of the house, including names of PV, battery ...
  houses[key] = HOUSE(key, info, fh.agents_dict, auction, seed) # initialize a house object
  houses[key].get_helics_subspubs(fh.get_agent_pubssubs(key, 'house', info)) # get subscriptions and publications for house meters
  houses[key].set_meter_mode() # set meter mode
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
  fig, (ax1, ax2, ax3, ax4, ax5) = plt.subplots(5)


# initialize time parameters
StopTime= int (hour_stop * 3600) # co-simulation stop time in seconds
StartTime = '2013-07-01 00:00:00 -0800' # co-simulation start time
dt_now = datetime.strptime (StartTime, '%Y-%m-%d %H:%M:%S %z')

dt = fh.dt # HELCIS period (1 seconds)
update_period = houses[last_house_name].hvac.update_period # state update period (15 seconds)
control_period = houses[last_house_name].hvac.update_period
request_period = houses[last_house_name].hvac.request_period   # local controller samples energy packet request period
market_period = auction.period # market period (300 seconds)
adjust_period = market_period # market response period (300 seconds)
fig_update_period = market_period # figure update time period
tnext_update = dt             # the next time to update the state
tnext_control = control_period
tnext_request = dt            # the next time to request
tnext_lmp = market_period - dt
tnext_bid = market_period - 2 * dt  # the next time controllers calculate their final bids
tnext_agg = market_period - 2 * dt  # the next time auction calculates and publishes aggregate bid
tnext_clear = market_period         # the next time clear the market
tnext_adjust = market_period       # the next time controllers adjust control parameters/setpoints based on their bid and clearing price
tnext_fig_update = market_period + dt   # the next time to update figures

time_granted = 0
time_last = 0

def plotFig1(curves):
    curves.update_curves(time_granted)
    ax1.cla()
    ax1.set_ylabel("VPP Load (kW)")
    # ax1.plot(curves.time_hour_curve, curves.curve_distri_load_p)
    ax1.plot(curves.time_hour_curve, curves.curve_vpp_load_p)
    ax1.legend(['VPP Load'])

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
    ax4.set_ylabel("Cleared Price ($)")
    ax4.plot(curves.time_hour_curve, curves.curve_cleared_price)

    ax5.cla()
    ax5.set_xlabel("Time (h)")
    ax5.set_ylabel("Percentage")
    ax5.plot(curves.time_hour_curve, curves.curve_hvac_on_ratio)
    ax5.plot(curves.time_hour_curve, curves.curve_buyer_ratio)
    ax5.plot(curves.time_hour_curve, curves.curve_seller_ratio)
    ax5.plot(curves.time_hour_curve, curves.curve_nontcp_ratio)
    ax5.legend(['HVAC-ON ratio', 'Buyer ratio', 'Seller ratio', 'None-participant ratio'])


    plt.pause(0.01)
    tnext_fig_update += fig_update_period
    figure = plt.gcf() 
    figure.set_size_inches(32, 18)
    plt.savefig('launch.png', bbox_inches='tight')

"""============================Substation Loop=================================="""

while (time_granted < StopTime):

  """ 1. step the co-simulation time """
  nextHELICSTime = int(min ([tnext_update,tnext_request,tnext_lmp, tnext_bid, tnext_agg, tnext_clear, tnext_adjust, StopTime]))
  time_granted = int (helics.helicsFederateRequestTime(fh.hFed, nextHELICSTime))
  time_delta = time_granted - time_last
  time_last = time_granted
  hour_of_day = 24.0 * ((float(time_granted) / 86400.0) % 1.0)
  dt_now = dt_now + timedelta(seconds=time_delta) # this is the actual time
  day_of_week = dt_now.weekday() # get the day of week
  hour_of_day = dt_now.hour # get the hour of the day


  """ 2. houses update state/measurements for all devices, 
         update schedule and determine the power needed for hvac,
         make power predictions for solar,
         make power predictions for house load"""
  if time_granted >= tnext_update:
    for key, house in houses.items():
      house.update_time(time_granted) # update time for all elements of the house
      house.update_measurements() # update measurements for all devices
      house.hvac.change_basepoint(hour_of_day, day_of_week) # update schedule
      house.hvac.determine_power_needed() # hvac determines if power is needed based on current state
      house.predict_solar_power() # predict the solar power generation
      house.predict_house_load()  # predict the house load
    vpp.get_vpp_load() # get the VPP load
    curves.record_state_statistics(time_granted, houses, auction, vpp) # record something
    tnext_update += update_period


  """ 3. houses launch basic real-time control actions (not post-market control)
      including the control for battery"""
  if time_granted >= tnext_control:
    for key, house in houses.items():
      if house.hasBatt:
        house.battery.auto_control() # real-time basic control of battery to track the HVAC load
      # house.hvac.auto_control()
    tnext_control += control_period


  """ 4. market gets the local marginal price (LMP) from the bulk power grid,"""
  if time_granted >= tnext_lmp:
    auction.get_lmp () # get local marginal price (LMP) from the bulk power grid
    auction.get_refload() # get distribution load from gridlabd
    for key, house in houses.items():
      house.get_lmp_from_market(auction.lmp) # houses get LMP from the market
    tnext_lmp += market_period


  """ 5. houses formulate and send their bids"""
  if time_granted >= tnext_bid:
    auction.clear_bids() # auction remove all previous records, re-initialize
    time_key = str(int(tnext_clear))
    fh.prosumer_metrics[time_key] = {}
    for key, house in houses.items():
      house.bid = house.formulate_bid() # bid is [bid_price, quantity, hvac.power_needed, role, unres_kw, name]
      fh.prosumer_metrics[time_key][house.name] = [house.bid[0], house.bid[1], house.bid[2], house.bid[3]]
      if hasMarket:
        auction.collect_bid(house.bid)
    tnext_bid += market_period


  """ 6. market aggreates bids from prosumers"""
  if time_granted >= tnext_agg:
    auction.aggregate_bids()
    auction.publish_agg_bids_for_buyer()
    tnext_agg += market_period


  """ 7. market clears the market """
  if time_granted >= tnext_clear:
    if hasMarket:
      auction.clear_market(tnext_clear, time_granted)
      auction.surplusCalculation(tnext_clear, time_granted)
      auction_info = auction.publish_cleared_market_information() # used to generate the observation for agent
      print("!!The cleared price is: ",auction.clearing_price)
      for key, house in houses.items():
        house.get_cleared_market_information(auction_info)
        house.calculate_reward()
        house.publish_meter_price()
        house.post_market_control(auction.market_condition, auction.marginal_quantity) # post-market control is needed


    time_key = str(int(tnext_clear))
    fh.auction_metrics [time_key] = {auction.name:[auction.clearing_price, auction.clearing_type, auction.consumerSurplus, auction.averageConsumerSurplus, auction.supplierSurplus]}
    curves.record_auction_statistics(time_granted, houses, auction)
    tnext_clear += market_period


  """ 8. prosumer demand response (adjust control parameters/setpoints) """
  if time_granted >= tnext_adjust:
    if has_demand_response:
      for key, house in houses.items():
        house.demand_response()
    tnext_adjust += market_period


  """ 9. visualize some results during the simulation"""
  if drawFigure and time_granted >= tnext_fig_update:
    plotFig1
   


"""============================ Finalize the metrics output ============================"""
curves.save_statistics(data_path)
print ('writing metrics', flush=True)
auction_op = open (data_path+'auction_' + metrics_root + '_metrics.json', 'w')
print(json.dumps(fh.auction_metrics), file=auction_op)
auction_op.close()
house_op = open (data_path+'house_' + metrics_root + '_metrics.json', 'w')
print(json.dumps(fh.prosumer_metrics), file=house_op)
house_op.close()

path_base = './data/' #prevuously fed_substation/data but already in substation folder
#secondPath_base = ''exp(dyB-1-3kw)''
exp1 = 'exp(dyB-1-3kw)'
path = path_base + exp1 +'/'
with open(path+'data.pkl', 'rb') as f:
       data_dict = pickle.load(f)

   # secondPath = '../demo-PET/fed_gridlabd/'
#os.chdir("/PEMT-CoSim-Test/PEMT-CoSim-Test/demo-PET/")
  #  secondPath2 = os.chdir('..')
   # secondPath = os.chdir('../')
  #  secondPath2 = os.chdir('../')
   # os.getcwd()
trialPath = '../'
filePath = 'fed_gridlabd/'      
with open('./data/exp(dyB-1-3kw)/house_TE_ChallengeH_metrics.json', encoding='utf-8') as f:  #used to be with open(filePath + ...)####
    prosumer_dict = json.loads(f.read()) # federate_config is the dict data structure
    f.close() 
#time_hour_auction = data_dict['time_hour_auction']

time_hour_auction = data_dict['time_hour_auction']
buyer_ratio = data_dict['buyer_ratio']
seller_ratio = data_dict['seller_ratio']
nontcp_ratio = data_dict['nontcp_ratio']
cleared_price = data_dict['cleared_price']
LMP = data_dict['LMP']

time_hour_system = data_dict['time_hour_system']
temp_mean = data_dict['temp_mean']
temp_max = data_dict['temp_max']
temp_min = data_dict['temp_min']
basepoint_mean = data_dict['basepoint_mean']
setpoint_mean = data_dict['setpoint_mean']

system_hvac_load = data_dict['system_hvac_load']
hvac_load_mean = data_dict['hvac_load_mean']
hvac_load_max = data_dict['hvac_load_max']
hvac_load_min = data_dict['hvac_load_min']
system_house_load = data_dict['system_house_load']
house_load_mean = data_dict['house_load_mean']
house_load_max = data_dict['house_load_max']
house_load_min = data_dict['house_load_min']
system_house_unres = data_dict['system_house_unres']
house_unres_mean = data_dict['house_unres_mean']
house_unres_max = data_dict['house_unres_max']
house_unres_min = data_dict['house_unres_min']

system_PV = data_dict['system_PV']
house_PV_mean = data_dict['house_PV_mean']
house_PV_max = data_dict['house_PV_max']
house_PV_min = data_dict['house_PV_min']

hvac_on_ratio = data_dict['hvac_on_ratio']

distri_load_p = data_dict['distri_load_p']
# distri_load_q = data_dict['distri_load_q']

vpp_load_p = data_dict['vpp_load_p']
vpp_load_q = data_dict['vpp_load_q']


house = 'F0_house_A6'
bids = []
prices = []
roles = []
quantitys = []
for i in range(36):  #range(len(time_hour_auction)):
    t = int((i+1)*300)
    bid = prosumer_dict[str(t)][house] # bid_price, quantity, hvac.power_needed, role
    price = bid[0]
    quantity = bid[1]
    role = bid[3]
    if role == 'seller':
        quantitys.append(int(-quantity/3))
        roles.append(-1)
    elif role == 'buyer':
        quantitys.append(int(quantity/3))
        roles.append(1)
    else:
        quantitys.append(0)
        roles.append(0)
    prices.append(price)


fig2, (ax11, ax12, ax13) = plt.subplots(3)
ax11.set_ylabel('Role', size = 13)
ax11.tick_params(axis='x', labelsize=13)
ax11.tick_params(axis='y', labelsize=13)
ax11.set_yticks((-1, 0, 1))
ax11.set_yticklabels(("seller", "none-\nptcpt","buyer"))
ax11.plot(time_hour_auction, roles, 's--', color = 'k', linewidth = 1)

ax12.set_ylabel('Bid-Quantity \n(packet)', size = 13)
ax12.tick_params(axis='x', labelsize=13)
ax12.tick_params(axis='y', labelsize=13)
ax12.plot(time_hour_auction, quantitys, 's--', color = 'k', linewidth = 1)

ax13.set_ylabel('Bid-Price \n($/kWh)', size = 13)
ax13.set_xlabel("Time (h)", size = 13)
ax13.tick_params(axis='x', labelsize=13)
ax13.tick_params(axis='y', labelsize=13)
ax13.plot(time_hour_auction, prices,  color = 'k', linewidth = 1.5)
ax13.plot(time_hour_auction, cleared_price, color = 'g', linewidth = 1.5)
ax13.legend(['bid price', 'cleared price'])


# plt.figure(1)
# time = time_hour_auction
# plt.plot(time, quantitys , 's-')
# plt.xlabel('Time (h)')
# plt.ylabel('Bid-Quantity (1 packet)')
#
# plt.figure(2)
# time = time_hour_auction
# plt.plot(time, prices , '*-')
# plt.xlabel('Time (h)')
# plt.ylabel('Bid-Price ($/kWh)')
# # plt.legend()




fig, (ax1, ax2, ax3, ax4) = plt.subplots(4)
ax1.set_ylabel('Power (kW)', size = 13)
ax1.tick_params(axis='x', labelsize=13)
ax1.tick_params(axis='y', labelsize=13)
ax1.plot(time_hour_system, system_PV, color = 'g', linewidth = 1.5)
ax1.plot(time_hour_system, system_house_load, color = 'b', linewidth = 1.5)
ax1.plot(time_hour_system, vpp_load_p, color = 'k', linewidth = 2)
# ax1.plot(time_hour_system, system_hvac_load)
# ax1.plot(time_hour_system, system_house_unres)
ax1.legend(['total PV generation', 'total house load', 'grid power flow'])#, 'total HVAC load', 'total base load'])

ax2.set_ylabel('Temperature \n(degF)', size = 13)
ax2.tick_params(axis='x', labelsize=13)
ax2.tick_params(axis='y', labelsize=13)
ax2.plot(time_hour_system, basepoint_mean,  '--', color = 'k', linewidth = 1.5)
ax2.plot(time_hour_system, temp_max, color = 'g', linewidth = 1)
ax2.plot(time_hour_system, temp_min, color = 'm', linewidth = 1)
ax2.plot(time_hour_system, temp_mean, color = 'b', linewidth = 1.5)
ax2.legend(['set-point', 'max', 'min', 'mean'])

ax3.set_ylabel('Cleared Price \n($/kWh)', size = 13)
ax3.tick_params(axis='x', labelsize=13)
ax3.tick_params(axis='y', labelsize=13)
ax3.plot(time_hour_auction, LMP, color = 'g', linewidth = 1.5)
ax3.plot(time_hour_auction, cleared_price, color = 'b', linewidth = 1.5)
ax3.legend(['local marginal price', 'cleared price'])

ax4.set_ylabel('Ratio', size = 13)
ax4.set_xlabel("Time (h)", size = 13)
ax4.tick_params(axis='x', labelsize=13)
ax4.tick_params(axis='y', labelsize=13)
ax4.plot(time_hour_system, hvac_on_ratio, color = 'k', linewidth = 1.5)
ax4.plot(time_hour_auction, buyer_ratio, color = 'b', linewidth = 1.5)
ax4.plot(time_hour_auction, seller_ratio, color = 'g', linewidth = 1.5)
ax4.plot(time_hour_auction, nontcp_ratio, color = 'm', linewidth = 1.5)

ax4.legend(['HVAC ON', 'buyer', 'seller', 'none-ptcp'])






# # system load, PV, house load
# plt.figure(1)
# time = time_hour_system
# plt.plot(time, vpp_load_p , label = "grid consumption")
# plt.plot(time, system_PV , label = "total PV generation")
# plt.plot(time, system_house_load , label = "total house load")
# plt.plot(time, system_hvac_load , label = "total HVAC load")
# plt.plot(time, system_house_unres , label = "total base load")
# plt.xlabel('Time (h)')
# plt.ylabel('Power (kW)')
# plt.legend()
#
#
# # temperate
# plt.figure(2)
# time = time_hour_system
# plt.plot(time, setpoint_mean , label = "average set-point")
# plt.plot(time, temp_max , label = "maximum")
# plt.plot(time, temp_min , label = "minimum")
# plt.plot(time, temp_mean , label = "mean")
# plt.xlabel('Time (h)')
# plt.ylabel('House Temperature (degF)')
# plt.legend()
#
# # cleared price
# plt.figure(3)
# time = time_hour_auction
# plt.plot(time, cleared_price )
# plt.xlabel('Time (h)')
# plt.ylabel('Price ($/kWh)')
#
# # ratio
# plt.figure(4)
# plt.plot(time_hour_auction, buyer_ratio, label = 'buyer ratio')
# plt.plot(time_hour_auction, seller_ratio, label = 'seller ratio')
# plt.plot(time_hour_auction, nontcp_ratio, label = 'none-participant ratio')
# plt.plot(time_hour_system, hvac_on_ratio, label = 'HVAC ON ratio')
# plt.xlabel('Time (h)', size = 14)
# plt.ylabel('Ratio', size = 14)
# plt.legend()

#############################################################################333


figure = plt.gcf() 
figure.set_size_inches(32, 18)
plt.savefig('launch2.png', bbox_inches='tight')


plt.show()


fh.destroy_federate()  # destroy the federate
fh.show_resource_consumption() # after simulation, print the resource consumption
plt.show()
# fh.kill_processes(True) # it is not suggested here because some other federates may not end their simulations, it will affect their output metrics


