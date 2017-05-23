
import os
import sys
import subprocess
import argparse
import uuid
import yaml
import hashlib
import pip
import base64
import logging
import zlib
logging.basicConfig()

import model
import studiologging as sl

from apscheduler.schedulers.background import BackgroundScheduler
from configparser import ConfigParser

class LocalExecutor(object):
    """Runs job while capturing environment and logging results.

    TODO: capturing state and results.
    """

    def __init__(self, configFile=None):
        self.config = self.get_default_config()
        if configFile:
            with open(configFile) as f:
                self.config.update(yaml.load(f))

        self.db = self.get_db_provider()
        self.logger = logging.getLogger('LocalExecutor')
        self.logger.setLevel(10)

    def run(self, filename, args, experimentName = None, saveWorkspace = True):
        if not experimentName:
            experimentName = self.get_unique_experiment_name()

        self.logger.info("Experiment name: " + experimentName)
        keyBase = 'experiments/' + experimentName + '/'
        self.db[keyBase + 'args'] = [filename] + args

        self.save_python_env(keyBase)

        env = os.environ.copy()
        sl.setup_model_directory(env, experimentName)
        modelDir = sl.get_model_directory(experimentName)
        logPath = os.path.join(modelDir, self.config['log']['name'])

        def save_workspace(keySuffix='workspace_latest/'):
            if saveWorkspace:
                self.save_dir('.', keyBase + keySuffix)

        def save_modeldir():
            self.save_dir(modelDir, keyBase + "modeldir/")
        
        save_workspace('workspace/')
        sched = BackgroundScheduler()
        sched.start()

        with open(logPath, 'w') as outputFile:
            p = subprocess.Popen(["python", filename] + args, stdout=outputFile, stderr=subprocess.STDOUT, env=env)
            ptail = subprocess.Popen(["tail", "-f", logPath]) # simple hack to show what's in the log file

            sched.add_job(save_modeldir,  'interval', minutes = self.config['saveWorkspaceFrequency'])
            sched.add_job(save_workspace, 'interval', minutes = self.config['saveWorkspaceFrequency'])
            
            try:
                p.wait()
            finally:
                ptail.kill()

                self.save_dir(modelDir, keyBase + 'modeldir/')
                save_workspace()
                sched.shutdown()
                
    
        
    def get_unique_experiment_name(self):
        return str(uuid.uuid4())

    def get_db_provider(self):
        assert 'database' in self.config.keys()
        dbConfig = self.config['database']
        assert dbConfig['type'].lower() == 'firebase'.lower()
        return model.FirebaseProvider(dbConfig['url'], dbConfig['secret'])

    def save_dir(self, localFolder, keyBase):
        self.logger.debug("saving workspace to keyBase = " + keyBase)
        for root, dirs, files in os.walk(localFolder, topdown=False):
            for name in files:
                fullFileName = os.path.join(root, name)
                self.logger.debug("Saving " + fullFileName)
                with open(fullFileName, 'rb') as f:
                    data = f.read()
                    sha = hashlib.sha256(data).hexdigest()
                    self.db[keyBase + sha + "/data"] = base64.b64encode(zlib.compress(bytes(data)))
                    self.db[keyBase + sha + "/name"] = name
                    
        self.logger.debug("Done saving")

    def save_python_env(self, keyBase):
            packages = [p._key + '==' + p._version for p in pip.pip.get_installed_distributions(local_only=True)]
            self.db[keyBase + "pythonenv"] = packages

    def get_default_config(self):
        defaultConfigFile = os.path.dirname(os.path.realpath(__file__))+"/defaultConfig.yaml"
        with open(defaultConfigFile) as f:
            return yaml.load(f)

def main(args=sys.argv):
    parser = argparse.ArgumentParser(description='TensorFlow Studio runner. Usage: studio-runner script <script_arguments>')
    parser.add_argument('script_args', metavar='N', type=str, nargs='+')
    parser.add_argument('--config', '-c', help='configuration file')

    parsed_args = parser.parse_args(args)
    exec_filename, other_args = parsed_args.script_args[0], parsed_args.script_args[1:]
    # TODO: Queue the job based on arguments and only then execute.
    LocalExecutor(parsed_args.config).run(exec_filename, other_args)
    

if __name__ == "__main__":
    main()