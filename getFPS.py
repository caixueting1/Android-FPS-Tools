# coding:utf-8

"""
首先先确保把pip升级到21.2.4(好像20以上都行), 否则安装adb_shell会报错
python版本3.7
pip install adb_shell就可以了
运行脚本后需要先手机确认一次授权
python getFPS.py output_file -loop
output_file:输出文件路径，给了就输出，不给就不输出到文件
-loop:是否循环执行
"""

from inspect import FrameInfo
import os
from posixpath import basename
import sys
import threading
import math
from time import sleep, time
from adb_shell.adb_device import AdbDeviceUsb
from adb_shell.auth.sign_pythonrsa import PythonRSASigner
from adb_shell.auth.keygen import keygen

# adbShell = "adb shell {cmdStr}"

# _platform =  platform.system()
# search_cmd = str()
# # print(_platform)
# if _platform == 'Windows':
#     search_cmd = 'findstr'
# elif _platform == 'Linux':
#     search_cmd = 'grep'
# else:
#     print('Unsupported OS')
#     exit(-1)

time_interval = 1

# 换成毫秒
def ns_to_ms(ns):
    return ns / 1000000

# 换成秒
def ns_to_s(ns):
    return ns / 1000000000
        
class ADBController:

    __instance_lock = threading.Lock()
    keygen_path = os.path.expanduser('~/.adb/adb_rsa')
    signer = None

    # Singleton
    def __new__(cls, *args, **kwargs):
        if not hasattr(ADBController, "_instance"):
            with ADBController.__instance_lock:
                if not hasattr(ADBController, "_instance"):
                    ADBController.__instance = object.__new__(cls)  
        return ADBController.__instance

    def __init__(self):
        self.check_keygen()
        self.device = AdbDeviceUsb()
        self.connect()

    # rsa密钥check，没有会生成新的
    def check_keygen(self):
        adb_rsa_path = os.path.expanduser('~/.adb')
        if not os.path.exists(adb_rsa_path):
            os.mkdir(adb_rsa_path)
        if not os.path.exists(ADBController.keygen_path):
            keygen(ADBController.keygen_path)
        
        with open(ADBController.keygen_path) as f:
            priv = f.read()
        with open(ADBController.keygen_path + '.pub') as f:
            pub = f.read()

        ADBController.signer = PythonRSASigner(pub, priv)

    # 连接设备
    def connect(self):
        if ADBController.signer:
            self.device.connect(rsa_keys=[ADBController.signer], auth_timeout_s=1)
    
    # 执行adb shell命令并返回输出，返回值是一个按行分割的list
    def execute(self, cmd) -> list:
        # str = adbShell.format(cmdStr=cmd)
        # print(str)
        # os.system(str)
        # os.system(cmd)
        if not self.device.available:
            print('device is not available.')
            return
        response = self.device.shell(cmd)
        return response.splitlines()

    # def exe_and_get_output(self, cmd):
        # str = adbShell.format(cmdStr=cmd)
        # print(str)
        # output = os.popen(str)
        # output_str = output.readlines()
        # return output_str

    # 这个用不了
    def getFPS(self):
        self.execute("dumpsys gfxinfo {appName} > fps.txt".format(appName=self.appName))

    # 获取当前SurfaceView（游戏得运行在最上）
    def get_packadgeName(self):
        package_name = str()
        out_line = self.execute("dumpsys SurfaceFlinger --list | grep SurfaceView")
        # print(out_line)
        for line in out_line:
            if line.find('SurfaceView') == 0:
                package_name = line
        print('get package name: ', package_name)
        return package_name

    # 获取帧信息，返回一个120行3列的数组，每行为一帧
    # 第一列表示应用程序绘制图像的时间点
    # 第二列表示在软件将帧提交到硬件绘制之前的垂直同步时间
    # 第三列表示绘制完成时间点
    # 单位是纳秒
    def get_frame_data(self, appName) -> list:
        self.execute("dumpsys SurfaceFlinger --latency-clear \"%s\"" % appName)
        sleep(time_interval)
        out_line = self.execute("dumpsys SurfaceFlinger --latency \"%s\"" % appName)

        refresh_period = int(out_line.pop(0))
        out_line.pop(0)
        out_line.pop(-1)

        frame_datas = list()

        for line in out_line:
            line = line.split('\t')
            if line[0] != '0':
                frame_datas.append([int(n) for n in line])

        # print(frame_datas)

        return refresh_period, frame_datas

    # 算FPS
    def calculate_FPS(self, refresh_period, frame_data):
        fps = 0
        frame_count = len(frame_data)

        # 取中间一列算，很别问我为啥，反正别人就是这么算的，我也跟着来了
        timestamp_start = frame_data[0][1]
        timestamp_end = 0
        
        # 最后一行有时候会出现maxlong值导致fps为0，暂时不知道原因，碰到就取上一行的为end
        for line in frame_data[::-1]:
            if line[1] != sys.maxsize:
                timestamp_end = line[1]
                break

        timestamp_interval = ns_to_s(timestamp_end - timestamp_start)
        fps = frame_count / timestamp_interval
        return fps

    # 算jank
    # The difference between the 1st and 3rd timestamp is the frame-latency.  
    # An interesting data is when the frame latency crosses a refresh period  
    # boundary, this can be calculated this way:  
    #  
    # ceil((C - A) / refresh-period)  
    #  
    # (each time the number above changes, we have a "jank").  
    # If this happens a lot during an animation, the animation appears  
    # janky, even if it runs at 60 fps in average.  
    def calculate_jank(self, refresh_period, frame_data):
        last_value = -1
        jank_times = 0

        for line in frame_data:
            cur_value = math.ceil((line[2] - line[0]) / refresh_period)
            # 第一帧不管
            if last_value == -1:
                last_value = cur_value
            # 状态改变，jank数++
            if cur_value != last_value:
                jank_times += 1
                last_value = cur_value
        
        jank_rate = jank_times / len(frame_data)
        return jank_rate


    # def test(self):
    #     rsp = self.execute('echo Test1')
    #     print(rsp)


def main(args):

    out_path = str()
    is_loop_run = False
    if len(args) > 1:
        if args[1] != '-loop':
            out_path = args[1]
        if args[-1] == '-loop':
            is_loop_run = True


    adb_controller = ADBController()
    # adb_controller.test()
    package_name = adb_controller.get_packadgeName()
    if not package_name:
        print('App not Find')
        return
    
    while(True):
        refresh_period, frame_data = adb_controller.get_frame_data(package_name)
        fps = adb_controller.calculate_FPS(refresh_period, frame_data)
        jank = adb_controller.calculate_jank(refresh_period, frame_data)
        refresh_rate = math.floor(1/ns_to_s(refresh_period))

        fps_info = 'FPS: %.2f\n' % fps
        jank_info = 'Jank: %.2f%%\n' % (jank * 100)
        refresh_rate_info = 'refresh_rate: %d\n' % refresh_rate

        print('----------------------------------------')
        print(fps_info)
        print(jank_info)
        print('----------------------------------------')

        if out_path:
            with open(out_path, 'a+') as f:
                f.write('---------------------------------------------------------\n')
                f.write(fps_info)
                f.write(jank_info)
                f.write(refresh_rate_info)
                for line in frame_data:
                    for element in line:
                        f.write('%d\t' % element)
                    f.write('\n')
                f.write('---------------------------------------------------------\n')

        if not is_loop_run:
            break

if __name__ == '__main__':
    main(sys.argv)