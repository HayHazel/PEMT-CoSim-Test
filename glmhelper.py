import json
import os
import pickle
import random
from datetime import timedelta

import glm

from scenario import PETScenario


class GlmGenerator:
    """
    A class used to define the functions for generating .glm for Gridlab-d federate.
    ...
    Attributes
    ----------

    Methods
    -------
    configure_minimum_timestep()
        Configure simulation timestep for .glm file
    configure_houses()
        Add houses objects in .glm file
    configure_PV()
        Add PV objects in .glm file
    configure_Bat()
        Add battery objects in .glm file
    configure_helics_msg()
        Add helics module in .glm file


    """

    def __init__(self, scenario: PETScenario):
        """
        Parameters
        ----------
        scenario: class object
            The GLM_Configuration class object which contains the configurations for
            .glm file of the GridLAB-D federate
        """
        self.scenario = scenario
        self.file_name_np = "TE_Challenge.glm"  # the file name of the .glm file without path added
        self.file_name = "./fed_gridlabd/" + self.file_name_np
        os.system("cp ./fed_gridlabd/glm-template/template.glm " + self.file_name + "")  # copy a standard .glm file
        with open("./fed_gridlabd/glm-template/template.glm", "r") as f:
            self.template = f.read()

        self.glm_code = ""
        # get configured time step configuration
        # self.minimum_timestep = config.minimum_timestep
        # self.helics_connected = config.helics_connected

        with open('./fed_gridlabd/glm-template/grid_meter_template', 'r') as f:
            self.grid_meter_template = f.read()
        with open('./fed_gridlabd/glm-template/house_template', 'r') as f:
            self.house_template = f.read()
        with open('./fed_gridlabd/glm-template/pv_template', 'r') as f:
            self.pv_template = f.read()
        with open('./fed_gridlabd/glm-template/ev_template', 'r') as f:
            self.ev_template = f.read()

        with open("template_houses.pkl", "rb") as f:
            self.template_houses = pickle.load(f)

        pass

    def write_template_houses(self):
        template_glm = glm.load("./fed_gridlabd/glm-template/TE_Challenge_TE30.glm")
        template_houses_list = [obj for obj in template_glm['objects'] if obj['name'] == 'house']
        with open("template_houses.pkl", "wb") as f:
            pickle.dump(template_houses_list, f)

    # def configure_minimum_timestep(self):
    #     """configure the minimum time step for .glm file
    #     """
    #     replaceInPattern(self.file_name, "{minimum_timestep}", str(self.minimum_timestep))

    def generate_glm(self):
        self.glm_code = self.template.replace("{minimum_timestep}", str(self.scenario.minimum_timestep))
        self.glm_code = self.glm_code.replace("{start_time}", self.scenario.start_time.strftime("'%Y-%m-%d %H:%M:%S'"))
        self.glm_code = self.glm_code.replace("{end_time}", self.scenario.end_time.strftime("'%Y-%m-%d %H:%M:%S'"))
        self.configure_vpp_infrastructure()
        self.generate_houses()
        self.configure_helics_msg()
        return self.glm_code.replace("{phase}", "A")

    def save(self, gridlab_path):
        glm = self.generate_glm()
        with open(f"{gridlab_path}/TE_Challenge.glm", "w") as f:
            f.write(glm)
        #
        # with open(f"{gridlab_path}/TE_Challenge_HELICS_gld_msg.json", "w") as f:
        #     f.write(json.dumps(helics_config, indent=4))

    def configure_helics_msg(self):
        """configure helics msg module in .glm file
        """
        self.glm_code += "\n\
module connection;\n\
object helics_msg {\n\
  configure gridlabd_helics_config.json;\n\
}\n"

    def configure_vpp_infrastructure(self):

        # code_text = ""
        #
        # ltt_code = self.grid_meter_template
        # ltt_code = ltt_code.replace("{vpp_idx}", "0")
        # ltt_code = ltt_code.replace("{phase}", "A")
        # code_text += ltt_code

        self.glm_code += self.grid_meter_template

    def generate_house_parameters(self):
        template_house = random.choice(self.template_houses)
        # air_temperature = float(template_house['attributes']['air_temperature']) + round(random.uniform(-1, 1))
        air_temperature = 73 + round(random.uniform(-1, 1))
        skew = int(template_house['attributes']['schedule_skew']) + random.randint(-10, 10)
        ZIP_code = ""
        for child in template_house['children']:
            if child['name'] == 'ZIPload':
                ZIP_code += "object ZIPload {\n"
                for attr in child['attributes']:
                    if attr == 'schedule_skew':
                        ZIP_code += '  ' + attr + ' ' + str(skew) + ';\n'
                    else:
                        ZIP_code += '  ' + attr + ' ' + child['attributes'][attr] + ';\n'
                ZIP_code += '};\n'

        return {
            "skew": skew,
            "Rroof": float(template_house['attributes']['Rroof']) + round(random.uniform(-1, 1), 2),
            "Rwall": float(template_house['attributes']['Rwall']) + round(random.uniform(-1, 1), 2),
            "Rfloor": float(template_house['attributes']['Rfloor']) + round(random.uniform(-1, 1), 2),
            "Rdoors": int(template_house['attributes']['Rdoors']),
            "Rwindows": float(template_house['attributes']['Rwindows']) + round(random.uniform(-0.1, 0.1), 2),
            "airchange_per_hour": float(template_house['attributes']['airchange_per_hour']) + round(
                random.uniform(-0.1, 0.1), 2),
            "total_thermal_mass_per_floor_area": float(
                template_house['attributes']['total_thermal_mass_per_floor_area']) + round(
                random.uniform(-0.2, 0.2), 2),
            "cooling_COP": float(template_house['attributes']['cooling_COP']) + round(random.uniform(-0.1, 0.1), 2),
            "floor_area": float(template_house['attributes']['floor_area']) + round(random.uniform(-20, 20), 2),
            "number_of_doors": int(template_house['attributes']['number_of_doors']),
            "air_temperature": air_temperature,
            "mass_temperature": air_temperature,
            "ZIP_code": ZIP_code
        }

    def generate_house(self, house_index, has_ev, has_pv):
        h_code = self.house_template
        h_code = h_code.replace("{vpp_idx}", "0")
        h_code = h_code.replace("{phase}", "A")
        h_code = h_code.replace("{house_idx}", str(house_index))
        h_par_dict = self.generate_house_parameters()
        h_code = h_code.replace("{skew}", str(h_par_dict['skew']))
        h_code = h_code.replace("{Rroof}", str(h_par_dict['Rroof']))
        h_code = h_code.replace("{Rwall}", str(h_par_dict['Rwall']))
        h_code = h_code.replace("{Rfloor}", str(h_par_dict['Rfloor']))
        h_code = h_code.replace("{Rdoors}", str(h_par_dict['Rdoors']))
        h_code = h_code.replace("{Rwindows}", str(h_par_dict['Rwindows']))
        h_code = h_code.replace("{airchange_per_hour}", str(h_par_dict['airchange_per_hour']))
        h_code = h_code.replace("{total_thermal_mass_per_floor_area}",
                                str(h_par_dict['total_thermal_mass_per_floor_area']))
        h_code = h_code.replace("{cooling_COP}", str(h_par_dict['cooling_COP']))
        h_code = h_code.replace("{floor_area}", str(h_par_dict['floor_area']))
        h_code = h_code.replace("{number_of_doors}", str(h_par_dict['number_of_doors']))
        h_code = h_code.replace("{air_temperature}", str(h_par_dict['air_temperature']))
        h_code = h_code.replace("{mass_temperature}", str(h_par_dict['mass_temperature']))
        h_code = h_code.replace("{ZIP_code}", str(h_par_dict['ZIP_code']))

        if has_ev:
            h_code += self.configure_ev(house_index)
        if has_pv:
            h_code += self.configure_pv(house_index)

        return h_code

    def generate_houses(self):
        houses = [
            self.generate_house(i, i < self.scenario.num_ev, i < self.scenario.num_pv)
            for i in range(self.scenario.num_houses)
        ]
        self.glm_code += "\n".join(houses)

        # return code_text
        # # write codes to the .glm file
        # with open(self.file_name, 'a+') as f:
        #     f.write(code_text)

    def configure_pv(self, house_index):

        pv_code = self.pv_template
        pv_code = pv_code.replace("{vpp_idx}", "0")
        pv_code = pv_code.replace("{phase}", "A")
        pv_code = pv_code.replace("{house_idx}", str(house_index))

        num_pv_panels = int(random.randint(8, 20))
        rated_power_solar = 480 * num_pv_panels  # W
        pv_code = pv_code.replace("{rated_power_solar}", str(rated_power_solar))
        pv_code = pv_code.replace("{maximum_dc_power}", str(rated_power_solar * 0.9))
        pv_code = pv_code.replace("{rated_power_inv}", str(rated_power_solar * 0.9))

        return pv_code

    def configure_ev(self, house_index: int):
        ev_code = self.ev_template.replace("{house_idx}", str(house_index))

        return ev_code
