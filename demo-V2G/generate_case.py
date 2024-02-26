# file: prepare_case.py
"""
Function:
        generate a co-simulation testbed based on user-defined configurations
last update time: 2021-11-11
modified by Yuanliang Li

"""
import argparse
import json
import pickle
from datetime import datetime

from fed_weather.TMY3toCSV import weathercsv
from glmhelper import GlmGenerator
from helics_config_helper import HelicsConfigHelper
from scenario import PETScenario

"""0. generate a glm file (TE_Challenge.glm) according to user's preference"""

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog='python3 generate_case.py',
        description='Generate a PET scenario for simulation')
    parser.add_argument("-a", "--name", type=str, default=None, help="scenario name")
    parser.add_argument("-n", "--num_houses", type=int, default=30, help="number of houses")
    parser.add_argument("-e", "--num_ev", type=int, default=30, help="number of EVs")
    parser.add_argument("-p", "--num_pv", type=int, default=30, help="number of PVs")
    parser.add_argument("-g", "--grid_cap", type=int, default=200000, help="grid power capacity (W)")
    # parser.add_argument("-w", "--work_charge_rate", type=int, default=7000, help="work charge rate")
    parser.add_argument("-f", "--figure_period", type=int, default=3600*24, help="figure drawing period (seconds)")
    parser.add_argument("-b", "--ev_buy_iqr_ratio", type=float, default=0.3, help="EV buy IQR ratio")
    parser.add_argument("-i", "--input_file", type=argparse.FileType('rb'), required=False)
    args = parser.parse_args()
    if args.input_file:
        scenario = pickle.load(args.input_file)
    else:
        scenario = PETScenario(
            scenario_name=args.name if args.name else f"scenario_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            num_houses=args.num_houses,
            num_ev=args.num_ev,
            num_pv=args.num_pv,
            grid_power_cap=args.grid_cap,
            start_time=datetime(2013, 7, 1, 0, 0, 0),
            end_time=datetime(2013, 7, 7, 0, 0, 0),
            workplace_charge_capacity=0,
            figure_period=args.figure_period,
            ev_buy_iqr_ratio=args.ev_buy_iqr_ratio
        )
        pickle.dump(scenario, open(f"scenarios/{scenario.name}.pkl", "wb"))
    pickle.dump(scenario, open("scenario.pkl", "wb"))
    print(f"Saved scenario {scenario.name} to scenario.pkl")

    GlmGenerator(scenario).save("fed_gridlabd")

    # configure weather data
    weathercsv(f"fed_weather/tesp_weather/AZ-Tucson_International_Ap.tmy3", 'weather.csv', scenario.start_time,
               scenario.end_time,
               scenario.start_time.year)

    # generate HELICS configs for fed_gridlabd and fed_substation
    helics_config_helper = HelicsConfigHelper(scenario)
    with open("fed_gridlabd/gridlabd_helics_config.json", "w") as f:
        json.dump(helics_config_helper.gridlab_config, f, indent=4)

    with open("fed_substation/substation_helics_config.json", "w") as f:
        json.dump(helics_config_helper.pet_config, f, indent=4)

    # update weather config
    weather_config_path = "fed_weather/weather_helics_config.json"
    weather_config = json.load(open(weather_config_path, "r"))
    weather_config["time_stop"] = f"{int((scenario.end_time - scenario.start_time).total_seconds() / 60)}m"
    json.dump(weather_config, open(weather_config_path, "w"), indent=4)

    # update pypower config
    pypower_config_path = "fed_pypower/te30_pp.json"
    pypower_config = json.load(open(pypower_config_path, "r"))
    pypower_config["Tmax"] = int((scenario.end_time - scenario.start_time).total_seconds())
    json.dump(pypower_config, open(pypower_config_path, "w"), indent=4)
