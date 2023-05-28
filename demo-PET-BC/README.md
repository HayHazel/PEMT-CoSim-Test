# PEMT-CoSim-Blockchain-Enabled

A Co-Simulation Platform For Packetized Energy Management and Trading with Blockchain Integrated with Blockchain

## 1. Description
This sub-project implements an Energy Trading Market using Fabric Blockchain, which interacts with the blockchain during program execution to enhance transaction transparency and fairness. Due to the need for Fabric Blockchain to run separately in Docker, it cannot be integrated into the Docker of PEMT-CoSim (running Docker in Docker would increase development difficulty). Therefore, in this project, PEMT-CoSim runs locally, while Fabric runs in Docker. PEMT-CoSim will interact with smart contracts on Fabric through the provided JavaScript program. We referred to the repository https://github.com/xuyangm/double-auction for the implementation of the Fabric code.




![image](../doc_images/PEMT-overview-withbc.png)
<center>PEMT-CoSim Architecture</center>

## 2. Installation
PEMT-CoSim runs natively on Linux, and the Fabric Blockchain runs inside multiple Docker containers in this subproject. To enable the operation, Docker, TESP, and Python packages need to be installed.

### 2.1 OS Environment

Please make sure using Ubuntu 20.04 LTS. The latest version of Ubuntu may not install the 1.0.0 version TESP.

Before the installation, the [Docker or Docker Desktop](https://www.docker.com/products/docker-desktop), and [Git](https://git-scm.com/) should be installed. 

### 2.2 Installation of TESP
Please run the command line below in sequence to install the TESP (https://github.com/pnnl/tesp)

    curl -L https://github.com/pnnl/tesp/releases/download/v1.0.0/tesp-1.0.0-linux-x64-installer.run -o tesp-1.0.0-linux-x64-installer.run
    chmod +x tesp-1.0.0-linux-x64-installer.run
    sudo ./tesp-1.0.0-linux-x64-installer.run


### 2.3 Python Environment

    cd ./demo-PET-BC
    pip install -r requirements.txt
### 2.4 Javascript Environment

    npm init
    npm install
    npm install fabric-ca-client && npm install fabric-network && npm install perf_hooks
    npm audit fix

## 3. Run Cases

- Set up the Fabric Blockchain Instance.
    ```
    cd ./demo-PET-BC/fabric/double-auction/application-javascript/test
    sudo ./reset.sh
    sudo ./start.sh
    ```
  The scripts will set up the blockchain with 9 dockers. You can visualize it using the VS code extension. Please try to use ./reset.sh to reset all docker instances if you encountered any unknown errors.

- Generate a study case of simulation.
    ```
    cd ./PEMT-CoSim/demo-PET-BC
    python3 generate_case.py 
    ```
  This python script will generate a study case based on user configuration

- Start the Blockchain-based energy trading market.
    ```
    cd /PEMT-CoSim/demo-PET/fed_substation/
    python3 launch_substation.py
    ```
  If executed successfully, the console will print out the bidding information and process.

## 4. File Directory 
Denote "(c)" as configuration file, "(o)" as output file.
* _generate_case.py_ : a python script to generate a study case based on user configuration
* _glmhelper.py_ : a class including functions to generate the .glm file
* _plotFig.py_ : makes plots for the case
* fed_gridlabd : folder for Gridlab-D federate
   * (c) _TE_Challenge.glm_ : define the distribution power grid for Gridlab-D
   * (c) _outputs_te.glm_ : define the output record for Gridlab-D
   * (c) _phase_A.player_ : define the phase A voltage for the unresponsive load in Gridlab-D
   * (c) _phase_B.player_ : define the phase B voltage for the unresponsive load in Gridlab-D
   * (c) _phase_C.player_ : define the phase C voltage for the unresponsive load in Gridlab-D
   * (c) _TE_Challenge_glm_dict.json_ : a dictionary of elements in Gridlab-D
   * (c) _TE_Challenge_HELICS_gld_msg.json_ : define HELICS message flows for Gridlab-D federate
   * (o) _billing_meter_TE_ChallengeH_metrics.json_
   * (o) _house_TE_ChallengeH_metrics.json_
   * (o) _inverter_TE_ChallengeH_metrics.json_
   * (o) _line_TE_ChallengeH_metrics.json_
   * (o) _capacitor_TE_ChallengeH_metrics.json_
   * (o) _regulator_TE_ChallengeH_metrics.json_
   * (o) _eplus_load.csv_
   * (o) _evchargerdet_TE_ChallengeH_metrics.json_
   * (o) _substation_TE_ChallengeH_metrics.json_
   * (o) _weather.csv_
   * (o) _gridlabd.log_
* fed_pypower : folder for PyPower federate
   * _launch_pypower.py_ : python script for launching the PyPower federate
   * (c) _te30_pp.json_ : define the transmission system in PyPower 
   * (c) _NonGLDLoad.txt_ : define the nonresponsive load in transmission system
   * (c) _pypowerConfig.json_ : define HELICS message flows for PyPower federate
   * (o) _bus_TE_ChallengeH_metrics.json.csv_
   * (o) _gen_TE_ChallengeH_metrics.json_
   * (o) _pypower.log_
* fed_energyplus : folder for EnergyPlus federate and EnergyPlus agent federate
   * (c) _*.idf_ : define the building for the EnergyPlus
   * (c) _helics_eplus.json_ : define HELICS message flows for EnergyPlus federate
   * (c) _helics_eplus_agent.json_ : define HELICS message flows for EnergyPlus agent federate
   * (o) _eplus_TE_ChallengeH_metrics.json_
   * (o) _output_
   * (o) _eplus.log_
   * (o) _eplus_agent.log_
* fed_substation : folder for substation federate
   * _launch_substation.py_ : python script for launching the substation federate. Moreover, in this example, it is also the main federate that can launch other federates at the same time.
   * _federate_helper.py_ : some functions for managing the federate, managing co-simulation, and data recording
   * _my_auction.py_ : user-defined double-auction class for the market
   * _PEM_Controller.py_ : define classes for PEM controller. 
   * _PEM_Coordinator.py_ : define classes for PEM coordinator. 
   * _PET_Prosumer.py_ : define classes for PET prosumers.
   * _env.py_ : define the reinforcement learning environment for prosumers.
   * _ddpg.py_ : deep determinstic policy gradient algorithm for reinforcement learnig agents.
   * (c) _TE_Challenge_agent_dict.json_ : define the market agent and HVAC controller agents
   * (c) _TE_Challenge_HELICS_substation.json_ : define HELICS message flows for substation federate
   * (o) _data_: a folder that save all data for post-processing
* fed_weather : folder for weather federate
   * _launch_weather.py_ : python script for launching the weather federate
   * (c) _weather.dat_ : weather data for one specific place in one specific time period
   * (c) _TE_Challenge_HELICS_Weather_Config.json_ : weather federate configuration file
   * (o) _weather.log_

* my_tesp_support_api: include the modified version of TESP support API
