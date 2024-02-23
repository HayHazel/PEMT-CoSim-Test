import pickle
import numpy as np
import json
import matplotlib.pyplot as plt

path_base = './fed_substation/data/'
exp1 = 'exp(dyB-1-3kw)'
path = path_base + exp1 +'/'
with open(path+'data.pkl', 'rb') as f:
    data_dict = pickle.load(f)

secondPath = './fed_gridlabd/'
with open(secondPath+'house_TE_ChallengeH_metrics.json', encoding='utf-8') as f:
    prosumer_dict = json.loads(f.read()) # federate_config is the dict data structure
    f.close()
#think we can ignore auction one as not referenced later in this file.
#with open(path+'auction_TE_ChallengeH_metrics.json', encoding='utf-8') as f:
#    auction_dict = json.loads(f.read()) # federate_config is the dict data structure
#    f.close()

#orignal path opens
#with open(path+'house_TE_ChallengeH_metrics.json', encoding='utf-8') as f:
#    prosumer_dict = json.loads(f.read()) # federate_config is the dict data structure
#    f.close()

#with open(path+'auction_TE_ChallengeH_metrics.json', encoding='utf-8') as f:
 #   auction_dict = json.loads(f.read()) # federate_config is the dict data structure
 #   f.close()



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
for i in range(len(time_hour_auction)):
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

plt.figure(1)
time = time_hour_auction
plt.plot(time, roles , 's-')
plt.xlabel('Time (h)')
plt.ylabel('Role')

plt.figure(2)
time = time_hour_auction
plt.plot(time, quantitys , 's-')
plt.xlabel('Time (h)')
plt.ylabel('Bid-Quantity (1 packet)')

plt.figure(3)
time = time_hour_auction
plt.plot(time, prices , '*-')
plt.xlabel('Time (h)')
plt.ylabel('Bid-Price ($/kWh)')
plt.legend()






#############################################################################333




plt.show()
