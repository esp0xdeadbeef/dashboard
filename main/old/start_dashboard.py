#!/usr/bin/ipython3
import os
import importlib.util


if (os.geteuid() != 0):
    print('run as admin')
    os._exit(-1)


dir_backend = os.path.realpath(__file__).split('/')[:-1]
#dir_backend.append('backend')
backend = "/".join(dir_backend)
pwd=backend + "/"
print(pwd)

for i in os.listdir(pwd):
    if "run_" in i and ".py" in i:
        run_location = pwd + i
        # print(run_location)
        break
else:
    print('couldn\'t find run_. exiting.')
    os._exit(-1)
#import class from file locations
def class_loader(class_name, location):
    spec = importlib.util.spec_from_file_location("module.name", location)
    class_importer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(class_importer)
    return eval("class_importer." + class_name)

run = class_loader('get_last_version_of_files', run_location)

write_cfg_location = run(pwd).get_specific_file('write_cfg_')
start_bot_location = run(pwd).get_specific_file('start_bot_')
print(write_cfg_location, start_bot_location)
os.popen("chmod +x \"" + write_cfg_location + "\"").read()
os.popen("chmod +x \"" + start_bot_location + "\"").read()


print(os.popen(write_cfg_location).read())
exec(open(write_cfg_location).read())
print("OEF write_cfg") 
exec(open(start_bot_location).read())
print("OEF start_bot")
