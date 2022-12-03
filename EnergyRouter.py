from locale import locale_encoding_alias
import os
import time
from time import sleep
import sys
import syslog
import configparser
import json
from collections import deque
import paho.mqtt.client as mqtt

SCRIPT_VERSION = "20221203"

CONFIG_FILE = "EnergyRouter.ini"
CONFIGSECTION_ROUTER = "router"
CONFIGSECTION_MQTT = "mqtt"
CONFIGSECTION_GRID = "grid"
CONFIGSECTION_DIMMER = "dimmer"
CONFIGSECTION_REGUL = "regulation"

MQTT_TOPIC_LWT = "RouterLWT"
MQTT_PAYLOAD_ONLINE = "online"
MQTT_PAYLOAD_OFFLINE = "offline"

ROUTERMODE_AUTO = -1
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
    global MAX_DIMMER_POURCENTAGE
    global MQTT_TOPIC_ROUTERMODE
    global MQTT_TOPIC_DIMMER_ONLINE

    global POWERFUNC

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
        MQTT_TOPIC_DIMMER_STATUS = confparser.get(CONFIGSECTION_DIMMER, "MQTT_TOPIC_DIMMER_STATUS")
        MAX_DIMMER_POURCENTAGE = int(confparser.get(CONFIGSECTION_DIMMER, "MAX_POURCENTAGE"))
        MQTT_TOPIC_ROUTERMODE =  confparser.get(CONFIGSECTION_DIMMER, "MQTT_TOPIC_ROUTERMODE")
        MQTT_TOPIC_DIMMER_ONLINE =  confparser.get(CONFIGSECTION_DIMMER, "MQTT_TOPIC_DIMMER_ONLINE")

        try:
            pf = confparser.get(CONFIGSECTION_REGUL, "power_function")
            pflist = list(pf.split())
            POWERFUNC = [eval(i) for i in pflist]
            if len(POWERFUNC) != 10:
                raise Exception("Parameter must contain 10 numbers")
            POWERFUNC.insert(0, 0)
        except Exception as e:
            print(f"Error reading power function values ({e}).")
            print("Default linear power function used. 100% value is 2000W")
            POWERFUNC = [0,200, 400, 600, 800, 1000, 1200, 1400, 1600, 1800, 2000]

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
#        print("connected OK")
        try:
            client.publish(MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_LWT, MQTT_PAYLOAD_ONLINE, 0, retain=True)
#            print("mqtt subscription")
            subscr_result = client.subscribe([
                (MQTT_TOPIC_GRIDPOWER,0),
                (MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_ROUTERMODE, 0),
                (MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_DIMMER_ONLINE, 0)
            ])
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
    client.on_connect = on_MQTTconnect
    client.on_disconnect = on_MQTTdisconnect
    client.on_message = on_message
    client.message_callback_add(MQTT_TOPIC_GRIDPOWER, on_message_gridpower)
    client.message_callback_add(MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_ROUTERMODE, on_message_routermode)
    client.message_callback_add(MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_DIMMER_ONLINE, on_message_dimmeronline)
    client.will_set(MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_LWT, MQTT_PAYLOAD_OFFLINE, 0, retain=True)
    if len(MQTT_USERNAME) > 0:
        client.username_pw_set(username=MQTT_USERNAME, password=MQTT_PASSWORD)
    #    print("Connecting to broker ",MQTT_BROKER)
    try:
        client.connect(MQTT_BROKER, MQTT_PORT) #connect to broker
        client.loop_start()
    except Exception as e:
        print(f"MQTT connection failed: {e}")
        return False
    timeout = time.time() + 5
    while client.connection_rc == -1: #wait in loop
        if time.time() > timeout:
            break
        time.sleep(1)
    return client.connected_flag

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
    gridpower.setvalue(float(msg.payload))

def on_message_routermode(client, userdata, msg):
    global routermode
    routermode.set_mode(msg.payload)

def on_message_dimmeronline(client, userdata, msg):
    global DIMMER_IS_ONLINE
    DIMMER_IS_ONLINE = (msg.payload.decode("ascii") == "online")
    if DIMMER_IS_ONLINE:
        print("Dimmer is online")
        syslog.syslog(syslog.LOG_INFO, "Dimmer is online")
    else:
        print("Dimmer is offline")
        syslog.syslog(syslog.LOG_INFO, "Dimmer is offline")


def inbetween(minv, val, maxv):
    return min(maxv, max(minv, val))


class Router:
    def __init__(self, mqttclient, maxdimmerpourcentage, prop, integ, gridpower_bias):
        self._routersum = 0
        self.set_prop(prop)
        self.set_integ(integ)
        self.set_gridpower_bias(gridpower_bias)
        self._maxdimmerpourcentage = maxdimmerpourcentage
        self._mqttclient = mqttclient
        self._cnt_publish_status = 0
        self._cnt_set_dimmer = 0
        self._last_dimpercent = -1

    def set_prop(self, value):
        self._prop = value / POWERFUNC[-1]

    def set_integ(self, value):
        self._integ = value / POWERFUNC[-1]

    def set_gridpower_bias(self, value):
        self._gridpower_bias = value

    def set_power(self, mode, gridpower):
        if not DIMMER_IS_ONLINE:
            return
        if mode == ROUTERMODE_AUTO:
            self._set_power_auto(gridpower)
        else:
            if mode >= 0:
                # linearized
                _load = inbetween(0, mode, 100)
                _dimpercent = self._get_dimmerpercent(_load)
                _dimpercent = int(_dimpercent * 10) / 10
            else:
                # calibration mode : non linearized
                _dimpercent = inbetween(0, -mode, 100)
                _load = _dimpercent
            self._setdimmer(_dimpercent, _load)

    def _set_power_auto(self, gridpower):
        if gridpower is None:
            return
        else:
            diff = -gridpower + self._gridpower_bias
            self._routersum = self._routersum + diff

            _rsummax = self._maxdimmerpourcentage / self._integ
            self._routersum = inbetween(-100, self._routersum, _rsummax)

            pDiff = diff * self._prop
            iDiff = self._routersum * self._integ
            _load = inbetween(0, pDiff + iDiff, 100)
            _dimmerpercent = self._get_dimmerpercent(_load)
            _dimmerpercent = int(_dimmerpercent * 10) / 10
            self._setdimmer(_dimmerpercent, _load)
            if LOGLEVEL == LOGLEVEL_DEBUG:
                self._publish_status(gridpower, _dimmerpercent, pDiff, iDiff)

    def _get_dimmerpercent(self, loadpercent):
        # power values for dimmerpercent = 0,10,20...100%
        power_lin = loadpercent * POWERFUNC[-1] / 100
        for i in range(len(POWERFUNC)):
            if power_lin <= POWERFUNC[i]:
                dimpercent = 10 * ( i - 1 + (power_lin - POWERFUNC[i-1]) / (POWERFUNC[i] - POWERFUNC[i-1]))
                return dimpercent
        return 100


    def _setdimmer(self, dimpercent, loadpercent):
#   dim_percent is used by the dimmer
#   load_percent can be used to display percentage of power provided by the dimmer
#   only publish every 10th dimmerload value, unless its value changes
        CNT_MAX = 10
        try:
            if self._last_dimpercent != dimpercent:
                self._cnt_set_dimmer = CNT_MAX

            if self._cnt_set_dimmer >= CNT_MAX:
                if self._mqttclient.connected_flag:
                    dictPayload = {
                        "dim_percent": dimpercent,
                        "power_percent": loadpercent,
                        "power_estim": int(loadpercent * POWERFUNC[-1] / 100),
                        }
                    res = self._mqttclient.publish(MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_DIMMER_POWER, json.dumps(dictPayload), 0, False)
                    self._cnt_set_dimmer = 0
                    self._last_dimpercent = dimpercent
            else:
                self._cnt_set_dimmer += 1
        except:
            pass

    def _publish_status(self, lastPower, dimmerLoad, pDiff, iDiff):
    # publish current gridpower, dimmersetting, _dimmersum
        dictPayload = {
            "gridpower_W": lastPower,
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
        self._setdimmer(0,0)
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
        self._current_mode = ROUTERMODE_AUTO

    def set_mode(self, newvalue):
        try:
            self._current_mode = inbetween(-100, int(float(newvalue.decode("ascii"))), 100)
        except Exception as e:
            print(f"[Error] [Set Routermode] {e}")

    @property
    def current_mode(self):
        return self._current_mode


def read_regul():
    '''
    Re regulation parameters once every 30s
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


REGUL_PROP = None
REGUL_INTEG = None
GRIDPOWER_BIAS = None
DIMMER_IS_ONLINE = False
# accepted maximum interval between gridpower MQTT messages
TICK_GRIDPOWER_MAX = 30 #seconds

try:
    print(f"Energy Router {SCRIPT_VERSION}")
    print("Copyright (C) 2022 https://github.com/frtz13")
    print()

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
    router = Router(MQTT_client, MAX_DIMMER_POURCENTAGE, REGUL_PROP, REGUL_INTEG, GRIDPOWER_BIAS)
    cnt_readregul = 0
    tick_gridpower = 0
    router_off_no_gridpower_info = False
    MQTT_connect(MQTT_client)

    while True:
        sleep(1)
        read_regul()

        if (tick_gridpower >= TICK_GRIDPOWER_MAX) and (routermode.current_mode == ROUTERMODE_AUTO):
            # we switch off router in auto mode without news from grid power
            if not router_off_no_gridpower_info:
                router_off_no_gridpower_info = True
                router.switch_off()
                msg = "[Error] [Timeout] No gridpower info. Router switched off."
                print(msg)
                syslog.syslog(syslog.LOG_WARNING, msg)
        else:
            if router_off_no_gridpower_info:
                router_off_no_gridpower_info = False
                msg = "Gridpower info is back. Router switched back on."
                print(msg)
                syslog.syslog(syslog.LOG_WARNING, msg)
            router.set_power(routermode.current_mode, gridpower.currentvalue)
            if tick_gridpower < TICK_GRIDPOWER_MAX:
                tick_gridpower += 1

except KeyboardInterrupt: # trap a CTRL+C keyboard interrupt 
    router.switch_off()
    MQTT_terminate(MQTT_client)
    print()
    syslog.syslog(syslog.LOG_INFO, "Stopped")
