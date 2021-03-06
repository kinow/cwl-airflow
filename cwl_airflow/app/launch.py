import os
import re
import subprocess
import configparser
import shutil
from plistlib import load, dump
from airflow.utils.db import merge_conn
from airflow import models


class Launcher:

    __AIRFLOW_SCH = "~/Library/LaunchAgents/com.biowardrobe.airflow-scheduler.plist"
    __AIRFLOW_WEB = "~/Library/LaunchAgents/com.biowardrobe.airflow-webserver.plist"

    __airflow_home = None
    __airflow_cfg = None
    __sch_conf = None
    __web_conf = None
    __contents_dir = None


    def __init__(self, airflow_home = "~/airflow"):
        self.__contents_dir = os.path.dirname(os.path.abspath(os.path.join(__file__, "../../../../")))
        self.__airflow_home = os.path.expanduser(airflow_home)
        self.__airflow_cfg = os.path.join(self.__airflow_home, "airflow.cfg")
        self.__configure()


    def __configure(self):
        try:
            self.__sch_conf = self.__read_plist(os.path.expanduser(self.__AIRFLOW_SCH))
            self.__web_conf = self.__read_plist(os.path.expanduser(self.__AIRFLOW_WEB))
        except:
            default_conf_folder = os.path.join(os.path.dirname(os.path.abspath(os.path.join(__file__, "../"))), "scripts", "macos")
            self.__sch_conf = self.__read_plist(os.path.join(default_conf_folder, os.path.basename(self.__AIRFLOW_SCH)))
            self.__web_conf = self.__read_plist(os.path.join(default_conf_folder, os.path.basename(self.__AIRFLOW_WEB)))
            self.__update_variables()
            self.__update_shebang()
            self.__init_airflow_db()
            self.__update_airflow_config()
            self.__copy_dags()
            self.__add_connections()
            self.__write_plist(self.__sch_conf, os.path.expanduser(self.__AIRFLOW_SCH))
            self.__write_plist(self.__web_conf, os.path.expanduser(self.__AIRFLOW_WEB))


    def __read_plist(self, path):
        with open(path, 'rb') as fs:
            return load(fs)    


    def __write_plist(self, data, path):
        with open(path, 'wb') as fs:
            dump(data, fs)


    def __get_path(self):
        path_list = [
            os.path.join(self.__contents_dir, "Resources/python/bin"),
            os.path.join(self.__contents_dir, "Resources/app_packages/bin"),
            os.path.join(self.__contents_dir, "MacOS"),
            "/usr/local/bin",
            "/usr/local/sbin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin"
        ]
        return ":".join(dict.fromkeys(path_list).keys())


    def __get_pythonpath(self):
        pythonpath_list = [
            os.path.join(self.__contents_dir, "Resources/app"),
            os.path.join(self.__contents_dir, "Resources/app_packages")
        ]
        return ":".join(dict.fromkeys(pythonpath_list).keys())


    def __update_variables(self):
        path = self.__get_path()
        pythonpath = self.__get_pythonpath()
        airflow = os.path.join(self.__contents_dir, "Resources/app_packages/bin/airflow")
        log_sch = os.path.join(self.__airflow_home, os.path.splitext(os.path.basename(self.__AIRFLOW_SCH))[0])
        log_web = os.path.join(self.__airflow_home, os.path.splitext(os.path.basename(self.__AIRFLOW_WEB))[0])

        self.__sch_conf["EnvironmentVariables"]["PATH"] = path
        self.__web_conf["EnvironmentVariables"]["PATH"] = path
        self.__sch_conf["EnvironmentVariables"]["PYTHONPATH"] = pythonpath
        self.__web_conf["EnvironmentVariables"]["PYTHONPATH"] = pythonpath
        self.__sch_conf["EnvironmentVariables"]["AIRFLOW_HOME"] = self.__airflow_home
        self.__web_conf["EnvironmentVariables"]["AIRFLOW_HOME"] = self.__airflow_home
        self.__sch_conf["ProgramArguments"][0] = airflow
        self.__web_conf["ProgramArguments"][0] = airflow
        self.__sch_conf["WorkingDirectory"] = self.__airflow_home
        self.__web_conf["WorkingDirectory"] = self.__airflow_home
        self.__sch_conf["StandardErrorPath"] = log_sch + ".stderr"
        self.__sch_conf["StandardOutPath"] = log_sch + ".stdout"
        self.__web_conf["StandardErrorPath"] = log_web + ".stderr"
        self.__web_conf["StandardOutPath"] = log_web + ".stdout"


    def __update_shebang(self):
        lookup_dir = os.path.join(self.__contents_dir, "Resources/app_packages/bin")
        shebang = "#!{}".format(os.path.join(self.__contents_dir, "Resources/python/bin/python3"))
        for filename in os.listdir(lookup_dir):
            filename = os.path.join(lookup_dir, filename)
            if not os.path.isfile(filename):
                continue
            with open(filename, "rb") as f:
                try:
                    lines = f.read().decode("utf-8").splitlines()
                except UnicodeDecodeError:
                    continue
            if not lines:
                continue
            script = [shebang] + lines[1:]
            with open(filename, "wb") as f:
                f.write("\n".join(script).encode("utf-8"))


    def __init_airflow_db(self):
        env = {
            "AIRFLOW_HOME": self.__airflow_home,
            "PATH": self.__get_path(),
            "PYTHONPATH": self.__get_pythonpath()
        }
        subprocess.run(["airflow", "initdb"], env=env)


    def __get_configuration(self):
        conf = configparser.ConfigParser()
        conf.read(self.__airflow_cfg)
        return conf


    def __update_airflow_config(self):
        conf = self.__get_configuration()
        with open(self.__airflow_cfg, 'w') as f:
            try:
                conf.add_section('cwl')
            except configparser.DuplicateSectionError:
                pass
            conf.set("cwl", "tmp_folder", os.path.join(self.__airflow_home, 'tmp'))
            conf.set("core", "logging_level", "INFO")
            conf.set("core", "load_examples", "False")
            conf.set("core", "dags_are_paused_at_creation", "False")
            conf.set("webserver", "dag_default_view", "graph")
            conf.set("webserver", "dag_orientation", "TB")
            conf.set("webserver", "hide_paused_dags_by_default", "True")
            conf.write(f)


    def __copy_dags(self):
        conf = self.__get_configuration()
        source_dags_folder = os.path.join(os.path.dirname(os.path.abspath(os.path.join(__file__, "../"))), "dags")
        target_dags_folder = conf.get("core", "dags_folder")
        os.makedirs(target_dags_folder, mode=0o0775, exist_ok=True)
        for root, dirs, files in os.walk(source_dags_folder):
            for filename in files:
                if re.match(".*\.py$", filename) and filename != "__init__.py":
                    shutil.copy(os.path.join(root, filename), target_dags_folder)


    def __add_connections(self):
        merge_conn(models.Connection(conn_id = "process_report",
                                     conn_type = "http",
                                     host = "localhost",
                                     port = "3070",
                                     extra = "{\"endpoint\":\"/airflow/\"}"))


    def load(self):
        subprocess.run(["launchctl", "load", "-w", os.path.expanduser(self.__AIRFLOW_SCH)])
        subprocess.run(["launchctl", "load", "-w", os.path.expanduser(self.__AIRFLOW_WEB)])


    def unload(self):
        subprocess.run(["launchctl", "unload", os.path.expanduser(self.__AIRFLOW_SCH)])
        subprocess.run(["launchctl", "unload", os.path.expanduser(self.__AIRFLOW_WEB)])