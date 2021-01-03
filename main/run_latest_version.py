#!/usr/bin/python3
import os
import re
import argparse


class get_last_version_of_files():
    """give the workdir, this function will get all the latest files from
     format ***_XXXX_**** where the X's are integers. 
    It will take the highest number."""

    def __init__(self, wd):
        self.basepath = wd
        self.list_of_apps = {}
        self.replace_string = '**********************'
        self.list_dir()
        self.get_latest_versions(wd)

    def get_latest_versions(self, path):
        file = path.split('/')[-1]
        path_to_file = '/'.join(path.split('/')[:-1])
        file_name = file.split('/')[-1]
        file_splitted = file_name.split('.')
        #print(path_to_file, file_name, file_splitted)
        regular_exp = '[0-9][0-9][0-9][0-9]'  # a number between 0 and 9999
        nr = re.findall(regular_exp, path, 0)

        if (nr != []):
            nr = nr[0]
            #print(nr, path.replace(str(nr), ""))
            index = path.replace(str(nr), self.replace_string)
            try:
                #print(list_of_apps[index], path)
                if (self.list_of_apps[index] < nr):
                    self.list_of_apps[index] = nr
            except:
                self.list_of_apps[index] = nr

    def list_dir(self):
        basepath = self.basepath
        for fname in os.listdir(basepath):
            path = os.path.join(basepath, fname)
            if os.path.isdir(path):
                # skip directories
                continue
            else:
                self.get_latest_versions(path)

    def get_list(self):
        ret_list = []
        for i in self.list_of_apps.keys():
            a = i.replace(self.replace_string, self.list_of_apps[i].zfill(4))
            ret_list.append(a)
        return ret_list

    def get_specific_file(self, file_name_middle_part):
        path = [string for string in self.get_list() if re.match(
            re.compile('.*' + file_name_middle_part + '.*'), string)][0]
        return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--workdir', default=None)
    parser.add_argument('--specific_file', default=None)
    parser.add_argument('--args', default='')
    args = parser.parse_args()

    if args.workdir == None:
        execute_list = get_last_version_of_files(os.getcwd())
    else:
        execute_list = get_last_version_of_files(args.workdir)

    exe_list = []

    if args.specific_file is not None:
        exe_list.append(execute_list.get_specific_file(args.specific_file))
    else:
        # print(execute_list.get_list())
        for i in execute_list.get_list():
            if (__file__ in i):
                print(__file__, i)
                break
            else:
                exe_list.append(i)
    # reversed, easier to write_cfg first.
    # exe_list.reverse()
    for i in exe_list:
        print("Executing: " + i + " " + args.args)
        os.system(i + " " + args.args)
        print('OEF' + i + "\n")
    # print('EOF')
