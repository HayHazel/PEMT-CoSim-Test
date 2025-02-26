# V2GPET Cosimulation Environment

## Structure
The cosimulation has 5 federates in folders `fed_ev`, `fed_gridlabd`, `fed_pypower`, `fed_substation`, `fed_weather`. The main important code/business logic is in `fed_ev` (the EV federate, which simulates EV movement) and `fed_substation` (which simulates houses and the PET trading system)

```plaintext
.
├── docker
│   └── Dockerfile
├── fed_ev
│   ├── ev_profiles.py  # Script to generate EV movement profiles
│   ├── pet_ev.py       # Simulates single EV's movement and state of charge
│   └── emobpy_data
│       └── config_files      # Config for emobpy EV profile generation
├── fed_gridlabd
│   ├── glm-template
│   │   └── TE_Challenge_TE30.glm  # Source glm for template house data
│   └── TE_Challenge.glm           # Defines microgrid for GridLAB-D power flow simulation
├── fed_pypower
├── fed_substation
│   ├── PET_Prosumer.py       # Defines House, HVAC, PV, EV, and Grid trading behaviour
│   ├── market.py             # Defines the continuous double auction system
│   ├── trading_policies.py   # Defines trading policy used by EVs and PVs
│   ├── metrics
│   │   └── <scenario_name>   # Contains metrics from the simulation
│   ├── figures
│   │   ├── progress.svg      # Regularly updated plot of recent stats
│   │   └── ...               # Various detailed plots
│   └── recording.py          # Handles metrics collection and progress plot generation
├── fed_weather
│   └── weather.csv           # Contains weather data
├── scenarios
│   └── ....pkl               # Saved scenario details
├── generate_case.py          # Script to prepare a scenario for simulation
├── helics_config_helper.py   # Helps in creating HELICS config files
├── runner.json               # Defines federates and their launch commands
├── scenario.pkl              # Current scenario details
└── template_houses.pkl       # Template house data
```

## Docker Setup

First, build and run the Docker container using these commands:

1. Build the Docker image: `docker build -t v2gpet -f docker/Dockerfile .`
2. Run the Docker container, mounting the project directory as a volume and entering an interactive shell: `docker run -it --mount type=bind,source=<PATH_TO_THIS_DIR>,destination=/PEMT-CoSim --name v2gpet1 v2gpet`
3. Activate the Conda environment: `conda activate cosim`

## Usage
To run a simulation, you first need to generate EV movement profiles and prepare a simulation scenario. Then, use HELICS to run the simulation.

### Short Version

1. `cd fed_ev`
2. `python3 ev_profiles.py -n 30 -s '2013-07-01 00:00:00' -e '2013-07-05 00:00:00' -g`
3. `cd ..`
4. `python3 generate_case.py -a example -n 30 -p 30 -e 30 -g 100000 -f 7200 -b 0.0`
5. `helics run --path=runner.json`
6. `cd fed_substation`
7. `python3 make_figures.py -s '2013-07-01 00:00:00' -e '2013-07-05 00:00:00' -m metrics/example`

### Detailed Version
- Before running a simulation, EV movement profiles must be generated using the `fed_ev/ev_profiles.py` script (run this from inside `fed_ev`).
    - usage: `python3 ev_profiles.py [-h] [-n NUM_EV] [-s START_DATE] [-e END_DATE | -t TOTAL_HOURS] [-g | -f]`
      - e.g. `python3 ev_profiles.py -n 30 -s '2013-07-01 00:00:00' -e '2013-07-05 00:00:00' -g`
    - This will take a few moments to use the `emobpy` library to generate profiles using the `CAR_MODELS_DISTRIBUTION` and `USER_TYPES_DISTRIBUTION` in `fed_ev/ev_profiles.py` and the rules and data from `emobpy` in `fed_ev/emobpy_data/config_files`
    - Once this has finished, figures showing the mobility data can be generated if desired using the same script with the `-f` flag instead of `-g`
- Next, use the `generate_case.py` script in the root directory to prepare a scenario for simulation
    - usage: `python3 generate_case.py [-h] [-a NAME] [-n NUM_HOUSES] [-e NUM_EV] [-p NUM_PV] [-g GRID_CAP] [-f FIGURE_PERIOD] [-b EV_BUY_IQR_RATIO]`
      - e.g. `python3 generate_case.py -a example -n 30 -p 30 -e 30 -g 100000 -f 7200 -b 0.0`
    - This will:
        - Save the scenario details to `scenario.pkl`, also making a named copy in the `scenarios` folder for record
        - Generate the `fed_gridlabd/TE_Challenge.glm` file that defines the microgrid's components and electrical connections, for power flow simulation
        - Generate the HELICS config files `fed_gridlabd/gridlabd_helics_config.json`, `fed_substation/substation_helics_config.json` that define those HELICS federates and their publications and subscriptions
          - Creation of these configs is handled by `helics_config_helper.py` in the root directory
          - Note: at the moment the EV federate is not defined here, its config is generated by the `fed_ev/launch_ev.py` script at the start of the simulation.
        - Set up the weather data in `fed_weather/weather.csv`
        - Configure the end time of the pypower and weather federates' HELICS configs
- Once a scenario is generated, the simulation can be run using `helics run --path=runner.json`.
  - This uses the `runner.json` file in the root directory to define the federates and their launch commands, starting them all together
  - Metrics from the simulation are saved in `fed_substation/metrics/<scenario_name>`.
    - This directory contains pickled DataFrames split into chunks and numbered in chronological order.
    - The recording of these metrics the generation of progress plots are handled by `fed_substation/recording.py`, where the `HistoryRecorder` class acts as a generic recorder for (nested) properties of Python objects, and `SubstationRecorder` uses `HistoryRecorder`s to collect stats from the whole substation federate.
      - Note: this metrics collection can currently only record values in the substation federate. I started work on a specific metrics federate that could aggregate metrics from every federate more efficiently, but ran into a couple of issues and out of time and ended up backtracking for now - I think it would be better though and an easy fix at some point. The substation federate subscribes all of the interesting values right now anyway, so it's not a big deal.
  - While the simulation runs, a plot of recent stats is regularly updated (every FIGURE_PERIOD provided to `generate_case.py`) in `fed_substation/figures/progress.svg`
    - This plot only shows the recent data as redrawing a full plot takes a long time once there is several days of data
- During or after the simulation, full detailed plots can be produced using the `fed_substation/make_figures.py` script
  - usage: `make_figures [-h] [-s START_DATE] [-e END_DATE] [-a ALL | -m METRICS]`
    - e.g. `make_figures -s '2013-07-01 00:00:00' -e '2013-07-05 00:00:00' -m metrics/example`
  - This produces a variety of plots written to the `fed_substation/figures` directory
