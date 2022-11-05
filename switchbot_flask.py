
import argparse
import requests
from flask import Flask
from flask import jsonify
from flask_apscheduler import APScheduler
import datetime
import time
import logging
import logging.handlers
import subprocess
import threading

parser = argparse.ArgumentParser()
parser.add_argument("--server_port", type=int,
                    help="server port to use", default=5500)
# to get Room temperature
parser.add_argument("--sensor_host", type=str,
                    help="sensor host to use", default="192.168.1.28")
parser.add_argument("--sensor_port", type=int,
                    help="sensor port to use", default=5000)
# Device used to check presence
parser.add_argument("--ref_devices", type=str,
                    help="device address", default="FC:AA:81:6D:BF:76")
# treshold values
parser.add_argument("--scheduler_temp_min", type=int,
                    help="scheduler temperature treshold min", default=16.5)
parser.add_argument("--scheduler_temp_max", type=int,
                    help="scheduler temperature treshold max", default=18.5)
parser.add_argument("--scheduler_temp_max_night", type=int,
                    help="scheduler temperature treshold max night", default=17.5)
args = parser.parse_args()

app = Flask(__name__)
scheduler = APScheduler()
SWITCHBOT_STATUS = 'enabled'
SCHEDULER_STATE_ON = False
SCHEDULER_INTERVAL = 300
SCHEDULER_BOOST = False

SCHEDULER_START = 21            # start at 21:00
SCHEDULER_END = 5               # stop at 05:00
SCHEDULER_START_NIGHT = 23      # start night mode at 23:00
SCHEDULER_END_NIGHT = 8         # end night mode at 08:00
TEMP_THRESHOLD_MIN = args.scheduler_temp_min
TEMP_THRESHOLD_MAX = args.scheduler_temp_max
TEMP_THRESHOLD_MAX_NIGHT = args.scheduler_temp_max_night

DEVICE_LIST = []
device_config = [
    {
        "name": "Corridor",
        "address": 'FE:A5:6D:8D:0D:E4'
    },
    {
        "name": "Sofa",
        "address": "DD:7F:B5:EC:CF:49"
    },
    {
        "name": "Aqua",
        "address": "E8:89:82:A4:35:7F"
    }
]

class Device:
    def __init__(self, address, name) -> None:
        self.name = name
        self.address = address
        self.status = 0 # 0 = 'off', 1 = 'on', 2 = 'night'
        self.force = False
    
    def get_status_string(self):
        if self.status == 2:
            return 'night'
        elif self.status == 1:
            return 'on'
        else:
            return 'off'

    def get_info(self):
        return {"name": self.name, "address": self.address, "status": self.get_status_string()}

    def switch(self, state, retry=0):
        if state == self.get_status_string():
            logging.debug("No need to switch({}): {} - {}".format(state, self.name, self.address))
            return True
        elif state != self.get_status_string() and retry < 10:
            logging.debug("will switch({}): {} - {}".format(state, self.name, self.address))
            stdout = subprocess.Popen(["python3", "python-host/switchbot_py3.py", "-d" , self.address, "-c", "press"], stdout=subprocess.PIPE) # ugly but easy
            stdout.wait()
            result =  stdout.communicate()[0].decode("utf-8")
            if "successful" not in result:
                logging.debug("issue for switch - will retry ({})".format(retry))
                retry+=1
                self.switch(state, retry)
                return True
            else:
                self.status += 1
                if self.status >= 3: self.status = 0
                logging.debug("switch ok {}".format(self.get_status_string()))
                if state != self.get_status_string():
                    time.sleep(2)
                    self.switch(state, 0)
                return True
        if retry == 10:
            logging.debug("issue for switch - too many retry".format())
            return False
        return False

    def is_status(self, expected):
        return self.get_status_string() == expected

def scheduleTask():
    global SCHEDULER_BOOST, SCHEDULER_START, SCHEDULER_END, TEMP_THRESHOLD_MIN
    def in_between(now, start, end):
        if start <= end:
            return start <= now < end
        else:
            return start <= now or now < end

    logging.info("run scheduleTask")
    if SCHEDULER_BOOST or (datetime.datetime.today().weekday() in [4,5,6] or in_between(datetime.datetime.now().time(), datetime.time(SCHEDULER_START,5), datetime.time(SCHEDULER_END,5))):
        logging.debug("run scheduleTask - time is ok- mode on")
        mode = 'on'
        if in_between(datetime.datetime.now().time(), datetime.time(SCHEDULER_START_NIGHT,0), datetime.time(SCHEDULER_END_NIGHT,0)):
            logging.debug("run scheduleTask - time is ok - mode night")
            mode = 'night'
        url = "http://{}:{}".format(args.sensor_host, args.sensor_port)
        r = requests.get(url, headers={'Cache-Control': 'no-cache'}, timeout = 10)
        temp = r.json()["temperature"]
        logging.debug("run scheduleTask - temperature is {}".format(temp))
        if SCHEDULER_BOOST or is_ref_device_connected(args.ref_devices):
            logging.debug("run scheduleTask - ref device is connected")
            if SCHEDULER_BOOST: 
                logging.debug("run scheduleTask - scheduler boost on - will switch {}".format(mode))
                switch(mode)
            if temp < TEMP_THRESHOLD_MIN:
                logging.debug("run scheduleTask - will switch {}".format(mode))
                switch(mode)
            elif mode == 'night' and check_status('on') and temp < TEMP_THRESHOLD_MAX_NIGHT:
                logging.debug("run scheduleTask - switch from on to night - {} > {}".format(temp, TEMP_THRESHOLD_MAX_NIGHT))
                switch(mode)
            elif mode == 'night' and temp > TEMP_THRESHOLD_MAX_NIGHT:
                logging.debug("run scheduleTask - mode night - {} > {}".format(temp, TEMP_THRESHOLD_MAX_NIGHT))
                switch('off')
            elif temp > TEMP_THRESHOLD_MAX:
                logging.debug("run scheduleTask - {} > {}".format(temp, TEMP_THRESHOLD_MAX))
                switch('off')
            else:
                ...
        else:
            logging.debug("run scheduleTask - ref device is not connected - switch off")
            switch('off')
    else:
        logging.debug("run scheduleTask - switch off")
        switch('off')

def turn_off_scheduler():
    global SCHEDULER_STATE_ON
    logging.debug("run turn_off_scheduler()")
    if SCHEDULER_STATE_ON:
        scheduler.pause_job(id='Scheduled Task')
        logging.debug("run is pause_job()")
        SCHEDULER_STATE_ON = not SCHEDULER_STATE_ON

def is_ref_device_connected(device, retry=0):
    result = False
    if retry < 5 :
        logging.debug("run is_device_connected()")
        stdout = subprocess.Popen(["bluetoothctl", "connect", device], stdout=subprocess.PIPE) # ugly method to check device is at home
        stdout.wait()
        result = "Connected: yes" in stdout.stdout.read().decode("utf-8")
        if not result:
            retry+=1
            is_ref_device_connected(device, retry)
    logging.debug("ref device is {}".format(result))
    return result

def switch(state):
    global bt_addr_list, SWITCHBOT_STATUS, SCHEDULER_BOOST
    d_t_l = []
    if state == 'off':
        SCHEDULER_BOOST = False
    if SWITCHBOT_STATUS == 'enabled':
        for d in DEVICE_LIST:
            d_t = threading.Thread(target=d.switch, args=(state,))
            d_t_l.append(d_t)
            d_t.start()
        for d_t in d_t_l:
            d_t.join()

def check_status(expected):
    result = True
    for d in DEVICE_LIST:
        result &= d.is_status(expected)
    return result

@app.route('/manual/<mode>')
def manual(mode):
    logging.info('run /manual/{}'.format(mode))
    # turn_off_scheduler() # make sure scheduler is off
    switch(mode)
    res = check_status(mode)
    resp = jsonify(success=res)
    return resp

@app.route('/scheduler/boost')
def scheduler_boost():
    global SCHEDULER_BOOST
    SCHEDULER_BOOST = True
    resp = jsonify(success=True)
    return resp, 200
    
@app.route('/scheduler/<mode>')
def schedule_on(mode):
    global SCHEDULER_STATE_ON
    logging.info('run /scheduler/'+mode)
    if not SCHEDULER_STATE_ON and mode == 'on':
        scheduler.resume_job(id='Scheduled Task')
        SCHEDULER_STATE_ON = not SCHEDULER_STATE_ON
        resp = jsonify(success=True)
        return resp, 200
    elif SCHEDULER_STATE_ON and mode == 'off':
        SCHEDULER_STATE_ON = not SCHEDULER_STATE_ON
        turn_off_scheduler()
        resp = jsonify(success=True)
        return resp, 200
    else:
        resp = jsonify(success=False)
        return resp, 400

@app.route('/enable')
def enable():
    global SWITCHBOT_STATUS
    SWITCHBOT_STATUS = 'enabled'
    logging.info('run /enable')
    resp = jsonify(success=True)
    return resp

@app.route('/disable')
def disable():
    global SWITCHBOT_STATUS
    SWITCHBOT_STATUS = 'disabled'
    logging.info('run /disable')
    turn_off_scheduler()
    resp = jsonify(success=True)
    return resp

@app.route('/status')
def status():
    global SCHEDULER_STATE_ON, SCHEDULER_BOOST, TEMP_THRESHOLD_MIN, TEMP_THRESHOLD_MAX_NIGHT, TEMP_THRESHOLD_MAX, DEVICE_LIST
    res = []
    for d in DEVICE_LIST:
        res.append(d.get_info())
    logging.info('run /status')
    return { "global_status": SWITCHBOT_STATUS, "scheduler_on": SCHEDULER_STATE_ON, "scheduler_boost": SCHEDULER_BOOST, "temp": { "min":TEMP_THRESHOLD_MIN, "max_night": TEMP_THRESHOLD_MAX_NIGHT, "max": TEMP_THRESHOLD_MAX}, "devices": res}

@app.route('/test/ref_device')
def test_ref_device():
    is_connected = is_ref_device_connected(args.ref_devices)
    resp = jsonify(result=is_connected)
    return resp

# to edit threshold values
@app.route('/set_temp/<type>/<float:temp>')
def set_temp(type, temp):
    global TEMP_THRESHOLD_MIN, TEMP_THRESHOLD_MAX, TEMP_THRESHOLD_MAX_NIGHT
    if type == 'min' : TEMP_THRESHOLD_MIN = temp
    elif type == 'max' : TEMP_THRESHOLD_MAX = temp
    elif type == 'max_night' : TEMP_THRESHOLD_MAX_NIGHT = temp
    return "Value setted"

def log_setup():
    log_handler = logging.handlers.TimedRotatingFileHandler('heater.log', when='D', interval=7, backupCount=4)
    formatter = logging.Formatter('%(asctime)s %(message)s', '%b %d %H:%M:%S')
    log_handler.setFormatter(formatter)
    logger = logging.getLogger()
    logger.addHandler(log_handler)
    logger.setLevel(logging.DEBUG)

if __name__ == '__main__':
    for device in device_config:
        DEVICE_LIST.append(Device(device["address"], device["name"]))

    log_setup()
    logging.info('Start of programm')

    scheduler.add_job(id = 'Scheduled Task', func=scheduleTask, trigger="interval", seconds=SCHEDULER_INTERVAL)
    scheduler.start()
    scheduler.pause_job(id='Scheduled Task')

    app.run(host='0.0.0.0', port=args.server_port)
