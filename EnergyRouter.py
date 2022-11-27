import os
import time
from time import sleep
import sys
import configparser
import json
from collections import deque
import paho.mqtt.client as mqtt

SCRIPT_VERSION = "20221127"

CONFIG_FILE = "EnergyRouter.ini"
CONFIGSECTION_MQTT = "mqtt"
CONFIGSECTION_GRID = "grid"
CONFIGSECTION_DIMMER = "dimmer"

MQTT_TOPIC_LWT = "RouterLWT"
MQTT_PAYLOAD_ONLINE = "online"
MQTT_PAYLOAD_OFFLINE = "offline"

ROUTERMODE_AUTO = -1

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

        return True
    except Exception as e:
        errmsg = "Error when reading configuration parameters: " + str(e)
        print(errmsg)
#        syslog.syslog(syslog.LOG_ERR, errmsg)
        return False

def on_MQTTconnect(client, userdata, flags, rc):
    client.connection_rc = rc
    if rc == 0:
        client.connected_flag = True
#       print("connected OK")
        try:
            client.publish(MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_LWT, MQTT_PAYLOAD_ONLINE, 0, retain=True)
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
#        syslog.syslog(syslog.LOG_ERR, errMsgFull)

def on_MQTTdisconnect(client, userdata, rc):
#    print("disconnecting reason  "  + str(rc))
    client.connected_flag = False

def MQTT_connect(client):
    client.on_connect = on_MQTTconnect
    client.on_disconnect = on_MQTTdisconnect
    client.on_message = on_message
    client.message_callback_add(MQTT_TOPIC_GRIDPOWER, on_message_gridpower)
    client.message_callback_add(MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_ROUTERMODE, on_message_routermode)
    client.will_set(MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_LWT, MQTT_PAYLOAD_OFFLINE, 0, retain=True)
    if len(MQTT_USERNAME) > 0:
        client.username_pw_set(username=MQTT_USERNAME, password=MQTT_PASSWORD)
#    print("Connecting to broker ",MQTT_BROKER)
    try:
        client.connect(MQTT_BROKER, MQTT_PORT) #connect to broker
        client.loop_start()
    except Exception as e:
#        print("connection failed: " + str(e))
        return False
    timeout = time.time() + 5
    while client.connection_rc == -1: #wait in loop
        if time.time() > timeout:
            break
        time.sleep(1)
    if client.connected_flag:
        subscr_result = client.subscribe([
            (MQTT_TOPIC_GRIDPOWER,0),
            (MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_ROUTERMODE, 0)
        ])
        if subscr_result[0] != 0:
            print("[error] mqtt subscription failed: " + subscr_result[0])
        return True
    else:
        return False

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
    print("Message received-> " + msg.topic + " " + str(msg.payload))  # Print a received msg

def on_message_gridpower(client, userdata, msg):
    global gridpower
    global cntupdavg
#    print("Message received-> " + msg.topic + " " + str(msg.payload))  # Print a received msg
    gridpower.setvalue(float(msg.payload))
    cntupdavg = 0

def on_message_routermode(client, userdata, msg):
    global routermode
    routermode.set_mode(msg.payload)


def inbetween(minv, val, maxv):
    return min(maxv, max(minv, val))


class Router:
    def __init__(self, mqttclient, maxdimmerpourcentage):
        self._routersum = 0
        self._prop = 0.015
        self._integ = 0.015
        self._maxdimmerpourcentage = maxdimmerpourcentage
        self._mqttclient = mqttclient
        self._cnt_publish_status = 0
        self._cnt_set_dimmer = 0
        self._last_dimpercent = -1

    def set_power(self, mode, gridpower):
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
            diff = -gridpower - 5
            self._routersum = self._routersum + diff

            _rsummax = self._maxdimmerpourcentage / self._integ
            self._routersum = inbetween(-100, self._routersum, _rsummax)

            pDiff = diff * self._prop
            iDiff = self._routersum * self._integ
            _load = inbetween(0, pDiff + iDiff, 100)
            _dimmerpercent = self._get_dimmerpercent(_load)
            _dimmerpercent = int(_dimmerpercent * 10) / 10
            self._setdimmer(_dimmerpercent, _load)
            self._publish_status(gridpower, _dimmerpercent, pDiff, iDiff)

    def _get_dimmerpercent(self, loadpercent):
        powerfunc = [0, 11,26,60,120,221,378,597,880,1224,1635]
        # power values for dimmerpercent = 0,10,20...100%
        power_lin = loadpercent * powerfunc[-1] / 100
        for i in range(len(powerfunc)):
            if power_lin <= powerfunc[i]:
                dimpercent = 10 * ( i - 1 + (power_lin - powerfunc[i-1]) / (powerfunc[i] - powerfunc[i-1]))
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
                        "load_percent": loadpercent,
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
        self._arr_gridpower = new

    @property
    def currentvalue(self):
        return self._arr_gridpower


class RouterMode:
    # supported modes: -1 (Auto), 0 (off), 1..100 (constant value)
    def __init__(self):
        self._current_mode = ROUTERMODE_AUTO

    def set_mode(self, newvalue):
        try:
            self._current_mode = inbetween(-100, int(newvalue), 100)
        except Exception as e:
            print("[Error] [Set Routermode] " + str(e))

    @property
    def current_mode(self):
        return self._current_mode




#for i in range(10):
#    print(_dimmerload_lin(i * 10))
#exit()

try:
    print(f"Energy Router {SCRIPT_VERSION}")
    print("Copyright (C) 2022 https://github.com/frtz13")
    print()

    if not read_config():
        print("Please check configuration file and parameters")
#        syslog.syslog(syslog.LOG_WARNING, "Program stopped. Please check configuration file and parameters.")
        exit()

    print("Type ctrl-C to exit")
#    syslog.syslog(syslog.LOG_INFO, f"Version {SCRIPT_VERSION} running...")

#   init MQTT connection
    mqtt.Client.connected_flag = False # create flags in class
    mqtt.Client.connection_rc = -1
    MQTT_client = mqtt.Client("EnergyRouter")
    MQTT_connected = False
    lastPower = 0
    
    gridpower = GridPower()
    routermode = RouterMode()
    router = Router(MQTT_client, MAX_DIMMER_POURCENTAGE)
    cntupdavg = 0

    while True:
        if not MQTT_connected:
            MQTT_connected = MQTT_connect(MQTT_client)
        sleep(1)
        router.set_power(routermode.current_mode, gridpower.currentvalue)

except KeyboardInterrupt: # trap a CTRL+C keyboard interrupt 
    router.switch_off()
    MQTT_terminate(MQTT_client)
    print()
#    syslog.syslog(syslog.LOG_INFO, "Stopped")
