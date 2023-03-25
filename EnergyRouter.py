# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from locale import locale_encoding_alias
import os
import signal
import time
from time import sleep
import sys
import syslog
import configparser
import json
import math
# from collections import deque
import paho.mqtt.client as mqtt

SCRIPT_VERSION = "2023.03.25"

CONFIG_FILE = "EnergyRouter.ini"
CONFIGSECTION_ROUTER = "router"
CONFIGSECTION_MQTT = "mqtt"
CONFIGSECTION_GRID = "grid"
CONFIGSECTION_DIMMER = "dimmer"
CONFIGSECTION_REGUL = "regulation"

MQTT_TOPIC_LWT = "RouterLWT"
MQTT_PAYLOAD_ONLINE = "online"
MQTT_PAYLOAD_OFFLINE = "offline"

LOGLEVEL_DEBUG = "DEBUG"

def read_config():
    global MQTT_BROKER
    global MQTT_PORT
    global MQTT_USERNAME
    global MQTT_PASSWORD
    global MQTT_TOPIC_GRIDPOWER
    global MQTT_TOPIC_DIMMER_ROOT
    global MQTT_TOPIC_DIMMER_POWER
    global MQTT_TOPIC_DIMMER_STATUS
    global MAX_DIMMER_PERCENTAGE
    global MQTT_TOPIC_ROUTERMODE
    global MQTT_TOPIC_DIMMER_ONLINE
    global MQTT_TOPIC_DIM_MAX_POWER
    global LOAD_MAX_POWER
    global DIM_MAX_POWER
    global OPEN_LOOP_GAIN_RAW

    try:
        confparser = configparser.RawConfigParser()
        confparser.read(os.path.join(sys.path[0], CONFIG_FILE))

        MQTT_BROKER = confparser.get(CONFIGSECTION_MQTT, "BROKER")
        MQTT_PORT = int(confparser.get(CONFIGSECTION_MQTT, "TCP_PORT"))
        MQTT_USERNAME = confparser.get(CONFIGSECTION_MQTT, "USERNAME")
        MQTT_PASSWORD = confparser.get(CONFIGSECTION_MQTT, "PASSWORD")

        MQTT_TOPIC_GRIDPOWER = confparser.get(CONFIGSECTION_GRID, "MQTT_TOPIC_GRIDPOWER")

        MQTT_TOPIC_DIMMER_ROOT = confparser.get(CONFIGSECTION_DIMMER, "MQTT_TOPIC_DIMMER_ROOT")
        MQTT_TOPIC_DIMMER_POWER = confparser.get(CONFIGSECTION_DIMMER, "MQTT_TOPIC_DIMMER_POWER")
        MQTT_TOPIC_DIMMER_STATUS = confparser.get(CONFIGSECTION_REGUL, "MQTT_TOPIC_DIMMER_STATUS")
        MQTT_TOPIC_ROUTERMODE =  confparser.get(CONFIGSECTION_REGUL, "MQTT_TOPIC_ROUTERMODE")
        MQTT_TOPIC_DIMMER_ONLINE = confparser.get(CONFIGSECTION_DIMMER, "MQTT_TOPIC_DIMMER_ONLINE")

        try:
            MQTT_TOPIC_DIM_MAX_POWER = confparser.get(CONFIGSECTION_REGUL, "MQTT_TOPIC_DIM_MAX_POWER")
        except Exception:
            MQTT_TOPIC_DIM_MAX_POWER = ""

        LOAD_MAX_POWER =  int(confparser.get(CONFIGSECTION_REGUL, "LOAD_MAX_POWER_W"))
        if LOAD_MAX_POWER < 10:
            raise Exception("Need reasonable value for LOAD_MAX_POWER_W (> 10).")

        try:
            DIM_MAX_POWER = int(confparser.get(CONFIGSECTION_REGUL, "DIM_MAX_POWER_W"))
            if (DIM_MAX_POWER <10) or (DIM_MAX_POWER > LOAD_MAX_POWER):
                raise Exception(f"Need reasonable value for {DIM_MAX_POWER} (> 10 and not more than {LOAD_MAX_POWER}).")
        except Exception:
            DIM_MAX_POWER = LOAD_MAX_POWER

        try:
            olg_raw = confparser.get(CONFIGSECTION_REGUL, "regul_o_l_gain_raw")
            olg_raw_list = list(olg_raw.split(","))
            OPEN_LOOP_GAIN_RAW = [eval(i) for i in olg_raw_list]
            if len(OPEN_LOOP_GAIN_RAW) != 9:
                raise Exception("list must contain 9 numbers")
            OPEN_LOOP_GAIN_RAW.insert(0, 0)
            OPEN_LOOP_GAIN_RAW.append(100)
            if not strictly_increasing(OPEN_LOOP_GAIN_RAW):
                raise Exception("list of values must be strictly increasing, with values > 0 and < 100")
        except Exception as e:
            print(f"Error reading raw normalized open loop gain values ({e}).")
            print("Default linear power function used.")
            OPEN_LOOP_GAIN_RAW = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

        return True
    except Exception as e:
        errmsg = f"Error when reading configuration parameters [general]: {e}"
        print(errmsg)
        syslog.syslog(syslog.LOG_ERR, errmsg)
        return False

def read_config_regul():
    global REGUL_PROP
    global REGUL_INTEG
    global GRIDPOWER_BIAS
    global REGUL_Changed
    global LOGLEVEL

    try:
        confparser = configparser.RawConfigParser()
        confparser.read(os.path.join(sys.path[0], CONFIG_FILE))
        old_prop = REGUL_PROP
        old_integ = REGUL_INTEG
        old_gridpower_bias = GRIDPOWER_BIAS
        REGUL_PROP = float(confparser.get(CONFIGSECTION_REGUL, "prop"))
        REGUL_INTEG = float(confparser.get(CONFIGSECTION_REGUL, "integ"))
        try:
            GRIDPOWER_BIAS = float(confparser.get(CONFIGSECTION_REGUL, "gridpower_bias"))
        except Exception:
            GRIDPOWER_BIAS = 0

        REGUL_Changed = (old_prop != REGUL_PROP) and (old_prop is not None)
        REGUL_Changed = REGUL_Changed or ((old_integ != REGUL_INTEG) and (old_integ is not None))
        REGUL_Changed = REGUL_Changed or ((old_gridpower_bias != GRIDPOWER_BIAS) and (old_gridpower_bias is not None))
        if REGUL_Changed:
            msg = "Got new regulation parameters from INI file"
            print(msg)
            syslog.syslog(syslog.LOG_INFO, msg)
        
        try:
            LOGLEVEL = confparser.get(CONFIGSECTION_ROUTER, "loglevel")
        except Exception:
            LOGLEVEL = LOGLEVEL_DEBUG

        return True
    except Exception as e:
        errmsg = f"Error when reading configuration parameters [regulation]: {e}"
        print(errmsg)
        syslog.syslog(syslog.LOG_ERR, errmsg)
        return False

def on_MQTTconnect(client, userdata, flags, rc):
    client.connection_rc = rc
    if rc == 0:
        client.connected_flag = True
        msg = "Connected to MQTT broker"
        print(msg)
        syslog.syslog(syslog.LOG_INFO, msg)
        try:
            client.publish(MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_LWT, MQTT_PAYLOAD_ONLINE, 0, retain=True)
#            print("mqtt subscription")
            mqttsubscr = [
                (MQTT_TOPIC_GRIDPOWER, 0),
                (MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_ROUTERMODE, 0),
                (MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_DIMMER_ONLINE, 0)
            ]
            if len(MQTT_TOPIC_DIM_MAX_POWER) > 0:
                mqttsubscr.append( (MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_DIM_MAX_POWER, 0) )
            subscr_result = client.subscribe(mqttsubscr)
            if subscr_result[0] != 0:
                print("[error] mqtt subscription failed: " + subscr_result[0])
        except:
            pass
    else:
        errMsg = {
            1: "Connection refused - incorrect protocol version",
            2: "Connection refused - invalid client identifier",
            3: "Connection refused - server unavailable",
            4: "Connection refused - bad username or password",
            5: "connection not autorized"
            }
        errMsgFull = "Connection to MQTT broker failed. " + errMsg.get(rc, f"Unknown error: {str(rc)}.")
        print(errMsgFull)
        syslog.syslog(syslog.LOG_ERR, errMsgFull)

def on_MQTTdisconnect(client, userdata, rc):
    if rc != 0:
        if rc == 7:
            expl = ". Another router running?"
        else:
            expl = ""
        print(f"Unexpected MQTT disconnection. Reason: {rc}{expl}")
        syslog.syslog(syslog.LOG_WARNING, f"Unexpected MQTT disconnection. Reason: {rc}{expl}")
    client.connected_flag = False

def MQTT_connect(client):
    # returns True if we started the connection loop, False otherwise
    # the connection loop will take care of reconnections
    client.on_connect = on_MQTTconnect
    client.on_disconnect = on_MQTTdisconnect
    client.on_message = on_message
    client.will_set(MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_LWT, MQTT_PAYLOAD_OFFLINE, 0, retain=True)
    if len(MQTT_USERNAME) > 0:
        client.username_pw_set(username=MQTT_USERNAME, password=MQTT_PASSWORD)
    #    print("Connecting to broker ",MQTT_BROKER)
    try:
        client.connect(MQTT_BROKER, MQTT_PORT) #connect to broker
        client.message_callback_add(MQTT_TOPIC_GRIDPOWER, on_message_gridpower)
        client.message_callback_add(MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_ROUTERMODE, on_message_routermode)
        client.message_callback_add(MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_DIMMER_ONLINE, on_message_dimmeronline)
        if len(MQTT_TOPIC_DIM_MAX_POWER) > 0:
            client.message_callback_add(MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_DIM_MAX_POWER, on_message_dim_max_power)
        client.loop_start()
    except Exception as e:
        errMsg = f"MQTT connection failed: {e}. Will be retried."
        print(errMsg)
        syslog.syslog(syslog.LOG_WARNING, errMsg)
        return False
    timeout = time.time() + 5
    while client.connection_rc == -1: #wait in loop
        if time.time() > timeout:
            break
        time.sleep(1)
    return True

def MQTT_terminate(client):
    try:
        if client.connected_flag:
            res = MQTT_client.publish(MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_LWT, MQTT_PAYLOAD_OFFLINE, 0, retain=True)
#            if res[0] == 0:
#                print("mqtt go offline ok")
            MQTT_client.disconnect()
        sleep(1)
        client.loop_stop()
    except Exception as e:
        print("MQTT client terminated with exception: " + str(e))
        pass

def on_message(client, userdata, msg):
    print(f"MQTT Message received: {msg.topic} / {msg.payload}")

def on_message_gridpower(client, userdata, msg):
    global gridpower
    try:
        gridpower.setvalue(float(msg.payload))
    except Exception:
        print(f"[error] got invalid gridpower value via MQTT: {msg.payload}")

def on_message_routermode(client, userdata, msg):
    global routermode
    routermode.set_mode(msg.payload)

def on_message_dimmeronline(client, userdata, msg):
    global DIMMER_IS_ONLINE
    DIMMER_IS_ONLINE = (msg.payload.decode("ascii") == "online")
    if DIMMER_IS_ONLINE:
        mess = "Dimmer is online"
        print(mess)
        syslog.syslog(syslog.LOG_INFO, mess)
    else:
        mess = "Dimmer is offline"
        print(mess)
        syslog.syslog(syslog.LOG_INFO, mess)

def on_message_dim_max_power(client, userdata, msg):
    global router
    try:
        router.set_dim_max_power(float(msg.payload))
        mess = f"Got {MQTT_TOPIC_DIM_MAX_POWER} (MQTT): {float(msg.payload)}"
        print(mess)
        syslog.syslog(syslog.LOG_INFO, mess)
    except Exception:
        print(f"Got invalid MQTT payload for {MQTT_TOPIC_DIM_MAX_POWER}")


def inbetween(minv, val, maxv):
    return min(maxv, max(minv, val))

def strictly_increasing(L):
    return all(x<y for x, y in zip(L, L[1:]))


class Router:
    def __init__(self, mqttclient, prop, integ, gridpower_bias):
        self._routersum = 0
        self._dim_max_power = LOAD_MAX_POWER
        self.set_prop(prop)
        self.set_integ(integ)
        self.set_dim_max_power(DIM_MAX_POWER)
        self.set_gridpower_bias(gridpower_bias)
        self._mqttclient = mqttclient
        self._cnt_publish_status = 0
        self._cnt_set_dimmer = 0
        self._last_dimpercent = -1

    def set_prop(self, value):
        self._prop = value / LOAD_MAX_POWER

    def set_integ(self, value):
        self._integ = value / LOAD_MAX_POWER
        self.set_dim_max_power(self._dim_max_power)

    def set_gridpower_bias(self, value):
        self._gridpower_bias = value

    def set_dim_max_power(self, value):
        self._rsummax = 100 * value / LOAD_MAX_POWER / self._integ
        self._dim_max_power = value

    def set_power(self, routermode, gridpower):
        if not DIMMER_IS_ONLINE:
            return
        if routermode.in_auto_mode:
            self._set_power_auto(gridpower)
        else:
            _loadpercent = routermode.current_mode
            if _loadpercent >= 0:
                _dimpercent = self._get_dimmerpercent(_loadpercent)
                _dimpercent = int(_dimpercent * 10) / 10
                self._setdimmer(_dimpercent, _loadpercent)
            else:
                self._setdimmer(_loadpercent, _loadpercent)

    def _set_power_auto(self, gridpower):
        if gridpower is None:
            return
        else:
            diff = -gridpower + self._gridpower_bias
            self._routersum += diff
            if self._dim_max_power >= LOAD_MAX_POWER:
                _rsummax = self._rsummax
            else:
                _rsummax = self._rsummax - diff * self._prop / self._integ
            self._routersum = inbetween(-100, self._routersum, _rsummax)
            pDiff = diff * self._prop
            iDiff = self._routersum * self._integ
            _loadpercent = inbetween(0, pDiff + iDiff, 100)
            _dimmerpercent = self._get_dimmerpercent(_loadpercent)
            _dimmerpercent = int(_dimmerpercent * 100) / 100
            self._setdimmer(_dimmerpercent, _loadpercent)
            if LOGLEVEL == LOGLEVEL_DEBUG:
                self._publish_status(gridpower, _dimmerpercent, pDiff, iDiff)

    def _get_dimmerpercent(self, loadpercent):
         # calculate the dimmer% we need to get loadpercent output power percentage
         # we look for the corresponding interval among the points of the open_loop_gain_raw points
         # then we make a linear interpolation
        olg_raw = OPEN_LOOP_GAIN_RAW
        for i in range(len(olg_raw)):
            if loadpercent <= olg_raw[i]:
                dimpercent = 10 * ( i - 1 + (loadpercent - olg_raw[i-1]) / (olg_raw[i] - olg_raw[i-1]))
                return dimpercent
        return 100

    def _setdimmer(self, percent, loadpercent):
#   only publish every 10th dimmerload value, unless its value changes
        CNT_MAX = 10
        try:
            if self._last_dimpercent != percent:
                self._cnt_set_dimmer = CNT_MAX

            if self._cnt_set_dimmer >= CNT_MAX:
                if self._mqttclient.connected_flag:
                    dictPayload = {
                        "dim_percent": percent,
                        "power_estim": int(loadpercent * LOAD_MAX_POWER / 100),
                        }
                    res = self._mqttclient.publish(MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_DIMMER_POWER, json.dumps(dictPayload), 0, False)
                    self._cnt_set_dimmer = 0
                    self._last_dimpercent = percent
            else:
                self._cnt_set_dimmer += 1
        except:
            pass

    def _publish_status(self, lastPower, dimmerLoad, pDiff, iDiff):
        dictPayload = {
            "gridpower_W": lastPower,
            "tick": tick_gridpower,
            "dimmer": dimmerLoad,
            "sum": self._routersum,
            "pDiff": pDiff,
            "iDiff": iDiff,
            }
        payload = json.dumps(dictPayload)
        try:
            if self._mqttclient.connected_flag:
                self._cnt_publish_status += 1
                if self._cnt_publish_status % 1 == 0:
                    self._cnt_publish_status = 0
                    res = self._mqttclient.publish(MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_DIMMER_STATUS, payload, 0, False)
                    print("status", payload)
        except:
            pass

    def switch_off(self):
        self._setdimmer(0, 0)
        return


class GridPower:
    def __init__(self):
        self._arr_gridpower = None

    def setvalue(self, new):
        global tick_gridpower

        self._arr_gridpower = new
        tick_gridpower = 0

    @property
    def currentvalue(self):
        return self._arr_gridpower


class RouterMode:
    # supported modes: -1 (Auto), 0 (off), 1..100 (constant value)
 
    def __init__(self):
        self._ROUTERMODE_AUTO = -1
        self._current_mode = self._ROUTERMODE_AUTO

    def set_mode(self, newvalue):
        try:
            self._current_mode = inbetween(-100, int(float(newvalue.decode("ascii"))), 100)
            msg = f"Got RouterMode: {self._current_mode}"
            print(msg)
            syslog.syslog(syslog.LOG_WARNING, msg)
        except Exception as e:
            msg = (f"[Error] [Set Routermode] {e}")
            print(msg)
            syslog.syslog(syslog.LOG_WARNING, msg)

    @property
    def current_mode(self):
        return self._current_mode

    @property
    def in_auto_mode(self):
        return self._current_mode == self._ROUTERMODE_AUTO

def read_regul():
    '''
    Read regulation parameters once every 30s
    to avoid restart when experimenting
    '''
    global cnt_readregul

    if cnt_readregul >= 30:
        cnt_readregul = 0
        if read_config_regul():
            if REGUL_Changed:
                router.set_prop(REGUL_PROP)
                router.set_integ(REGUL_INTEG)
                router.set_gridpower_bias(GRIDPOWER_BIAS)
    else:
        cnt_readregul += 1


def check_gridpower_info():
    TICK_GRIDPOWER_MAX = 120 #seconds

    global router_off_no_gridpower_info
    global tick_gridpower

    if (tick_gridpower >= TICK_GRIDPOWER_MAX):
        # we switch off router in auto mode without news from grid power
        if not router_off_no_gridpower_info:
            router_off_no_gridpower_info = True
            msg = "[Timeout] No gridpower info. Dimmer switched off."
            print(msg)
            syslog.syslog(syslog.LOG_WARNING, msg)
    else:
        if router_off_no_gridpower_info:
            msg = "Gridpower info available. Dimmer switched on."
            print(msg)
            syslog.syslog(syslog.LOG_INFO, msg)
            router_off_no_gridpower_info = False
        if tick_gridpower < TICK_GRIDPOWER_MAX:
            tick_gridpower += 1


def handler_stop_signals(sig, frame):
    global termination_request
    termination_request = True


REGUL_PROP = None
REGUL_INTEG = None
GRIDPOWER_BIAS = None
DIMMER_IS_ONLINE = False
# accepted maximum interval between gridpower MQTT messages
termination_request = False

try:
    print(f"Energy Router {SCRIPT_VERSION}")
    print("Copyright (C) 2022 https://github.com/frtz13")
    print()

    signal.signal(signal.SIGINT, handler_stop_signals)
    signal.signal(signal.SIGTERM, handler_stop_signals)

    if not read_config():
        print("Please check configuration file and parameters")
        syslog.syslog(syslog.LOG_WARNING, "Program stopped. Please check configuration file and parameters.")
        exit()
    if not read_config_regul():
        print("[regul] Please check configuration file and parameters.")
        syslog.syslog(syslog.LOG_WARNING, "Program stopped. [regul] Please check configuration file and parameters.")
        exit()

    print("Type ctrl-C to exit")
    syslog.syslog(syslog.LOG_INFO, f"Version {SCRIPT_VERSION} running...")

#   init MQTT connection
    mqtt.Client.connected_flag = False # create flags in class
    mqtt.Client.connection_rc = -1
    MQTT_client = mqtt.Client("EnergyRouter")
    
    gridpower = GridPower()
    routermode = RouterMode()
    router = Router(MQTT_client, REGUL_PROP, REGUL_INTEG, GRIDPOWER_BIAS)
    cnt_readregul = 0
    tick_gridpower = 0
    router_off_no_gridpower_info = None
    MQTT_connection_loop_running = False
    sleep_delay = 1

    while True:
        if termination_request:
            raise KeyboardInterrupt()

        sleep(sleep_delay)

        if not MQTT_connection_loop_running:
            MQTT_connection_loop_running = MQTT_connect(MQTT_client)
            if MQTT_connection_loop_running:
                sleep_delay = 1
            else:
                sleep_delay = 30 #avoid too many warnings at system start
                continue

        read_regul()

        check_gridpower_info()
        if router_off_no_gridpower_info and routermode.in_auto_mode:
            router.switch_off()
        else:
            router.set_power(routermode, gridpower.currentvalue)

except KeyboardInterrupt: # trap a CTRL+C keyboard interrupt 
    router.switch_off()
    MQTT_terminate(MQTT_client)
    print()
    syslog.syslog(syslog.LOG_INFO, "Stopped")
