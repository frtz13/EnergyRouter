import os
import time
from time import sleep
import sys
import configparser
import json
from collections import deque
import paho.mqtt.client as mqtt

SCRIPT_VERSION = "20221110"

CONFIG_FILE = "EnergyRouter.ini"
CONFIGSECTION_MQTT = "mqtt"
CONFIGSECTION_GRID = "grid"
CONFIGSECTION_DIMMER = "dimmer"

MQTT_TOPIC_LWT = "/LWT"
MQTT_PAYLOAD_ONLINE = "online"
MQTT_PAYLOAD_OFFLINE = "offline"


def read_config():
    global MQTT_BROKER
    global MQTT_PORT
    global MQTT_USERNAME
    global MQTT_PASSWORD
    global MQTT_TOPIC
    global MQTT_TOPIC_GRIDPOWER
    global MQTT_TOPIC_DIMMER_ROOT
    global MQTT_TOPIC_DIMMER_POWER
    global MQTT_TOPIC_DIMMER_STATUS

    try:
        confparser = configparser.RawConfigParser()
        confparser.read(os.path.join(sys.path[0], CONFIG_FILE))

        MQTT_BROKER = confparser.get(CONFIGSECTION_MQTT, "BROKER")
        MQTT_PORT = int(confparser.get(CONFIGSECTION_MQTT, "TCP_PORT"))
        MQTT_USERNAME = confparser.get(CONFIGSECTION_MQTT, "USERNAME")
        MQTT_PASSWORD = confparser.get(CONFIGSECTION_MQTT, "PASSWORD")
        MQTT_TOPIC = confparser.get(CONFIGSECTION_MQTT, "TOPIC")

        MQTT_TOPIC_GRIDPOWER = confparser.get(CONFIGSECTION_GRID, "MQTT_TOPIC_GRIDPOWER")

        MQTT_TOPIC_DIMMER_ROOT = confparser.get(CONFIGSECTION_DIMMER, "MQTT_TOPIC_DIMMER_ROOT")
        MQTT_TOPIC_DIMMER_POWER = confparser.get(CONFIGSECTION_DIMMER, "MQTT_TOPIC_DIMMER_POWER")
        MQTT_TOPIC_DIMMER_STATUS = confparser.get(CONFIGSECTION_DIMMER, "MQTT_TOPIC_DIMMER_STATUS")

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
            client.publish(MQTT_TOPIC + MQTT_TOPIC_LWT, MQTT_PAYLOAD_ONLINE, 0, retain=True)
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
    client.will_set(MQTT_TOPIC + MQTT_TOPIC_LWT, MQTT_PAYLOAD_OFFLINE, 0, retain=True)
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
        subscr_result = client.subscribe(MQTT_TOPIC_GRIDPOWER)
        if subscr_result[0] == 0:
            client.message_callback_add(MQTT_TOPIC_GRIDPOWER, on_message_gridpower)
        else:
            print("[error] mqtt subscription failed: " + subscr_result[0])
        return True
    else:
        return False

def MQTT_terminate(client):
    try:
        if client.connected_flag:
            res = MQTT_client.publish(MQTT_TOPIC + MQTT_TOPIC_LWT, MQTT_PAYLOAD_OFFLINE, 0, retain=True)
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
    gridpower.addvalue(float(msg.payload))
    cntupdavg = 0


class Router:
    def __init__(self, mqttclient):
        self._routersum = 0
        self._prop = 0.03
        self._integ = 0.02
        self._maxdimmerpourcentage = 60
        self._mqttclient = mqttclient
        self._cnt_publish_status = 0

    def set_power(self, lastPower):
        if lastPower is None:
            return
        else:
            diff = -lastPower
            self._routersum = self._routersum + diff
            pDiff = diff * self._prop
            iDiff = self._routersum * self._integ
            _dimmerload = int(pDiff + iDiff)
            _dimmerload = min(_dimmerload, 100)
            _dimmerload = max(_dimmerload, 0)
            _rsummax = self._maxdimmerpourcentage / self._integ
            self._routersum = min(self._routersum, _rsummax)
            self._routersum = max(self._routersum, -100)
            self._setdimmer(_dimmerload)
            self._publish_status(lastPower, _dimmerload, pDiff, iDiff)


    def _setdimmer(self, dimmerload):
        try:
            if self._mqttclient.connected_flag:
                res = self._mqttclient.publish(MQTT_TOPIC_DIMMER_ROOT + "/" + MQTT_TOPIC_DIMMER_POWER, str(dimmerload), 0, False)
#                print("dimmerload: ", dimmerload)
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
        self._setdimmer(0)
        return

class GridPower:
    def __init__(self):
        self._arr_gridpower = deque([], maxlen=1)

    def addvalue(self, new):
        self._arr_gridpower.append(new)

    def duplicate_latest(self):
        if len(self._arr_gridpower) > 0:
            self._arr_gridpower.append(self._arr_gridpower[-1])

    @property
    def currentvalue(self):
        if len(self._arr_gridpower) == 0:
            return None
        else:
            return sum(self._arr_gridpower) / len(self._arr_gridpower)

    @property
    def latestvalue(self):
        if len(self._arr_gridpower) == 0:
            return None
        else:
            return self._arr_gridpower[-1]

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
    connect_to_MQTT = MQTT_BROKER != ""
    mqtt.Client.connected_flag = False # create flags in class
    mqtt.Client.connection_rc = -1
    MQTT_client = mqtt.Client("EnergyRouter")
    MQTT_connected = False
    lastPower = 0
    
    gridpower = GridPower()
    router = Router(MQTT_client)
    cntupdavg = 0

    while True:
        if not MQTT_connected and connect_to_MQTT:
            MQTT_connected = MQTT_connect(MQTT_client)
        sleep(2)
#        print(gridpower.currentvalue, gridpower.latestvalue)
        router.set_power(gridpower.currentvalue)
        cntupdavg += 1
        if cntupdavg % 3 == 0:
            gridpower.duplicate_latest()

except KeyboardInterrupt: # trap a CTRL+C keyboard interrupt 
    router.switch_off()
    MQTT_terminate(MQTT_client)
    print()
#    syslog.syslog(syslog.LOG_INFO, "Stopped")