# Running Energy Router in AppDaemon

Install AppDaemon from the Community Add-on store, if you did not already.

## Configure AppDaemon

Edit the /config/appdaemon/appdaemon.yaml file. A basic version has been put in place at installaton time. Add the missing parameters. See notes below.

```
secrets: /config/secrets.yaml
appdaemon:
  latitude: 52.379189
  longitude: 4.899431
  elevation: 2
  time_zone: Europe/Amsterdam
  plugins:
    HASS:
      type: hass
      app_init_delay: 10
    MQTT:
      type: mqtt
      namespace: mqtt
      client_id: appdaemon-unique-id
      client_host: !secret mqtt_broker
      client_user: !secret mqtt_user
      client_password: !secret mqtt_password
      client_topics:
        - some/nonexisting/topic
http:
  url: http://127.0.0.1:5050
admin:
api:
hadashboard:
logs:
  error_log:
    filename: /config/appdaemon/logs/error.log
  main_log:
    filename: /config/appdaemon/logs/main.log
  access_log:
    filename: /config/appdaemon/logs/access.log
  diag_log:
    filename: /config/appdaemon/logs/diag.log
  energyrouter_log:
    name: energyrouter
    filename: /config/appdaemon/logs/energyrouter.log
```

**Notes:**

Make sure to have the required values in your secrets.yaml file.

client_topics: just leave this parameter as it is. Setting this parameter to "none" will produce annoying warning messages when subscribing to mqtt topics in code.

logs: make sure to also create a "logs"-folder in /config/appdaemon to provide a place for the logs.

When done, restart AppDaemon.

Open its web interface on port 5050, and have a look at the main log. It is important to configure the MQTT-plugin correctly, so that it starts up smoothely. Check in the `main`log.

## Install Energy Router

Copy `energy_router.py` and `energy_router.yaml` from the AppDeamon folder of this repository to the /config/appdaemon/apps folder of your H.A. installation.

Note: you can use *File editor* add-on to upload files from your workstation to your H.A. installation.

## Configure Energy Router

Open energy_router.yaml in your favourite text editor. AddDaemon will restart the Energy Router as soon as you save the file.

go: switches the Energy Router on or off.

sensor_gridpower: enter the name of the sensor connected to your energy meter, returning the power consumed by the household. Power should be in W. Positive values for consumption, négative values for sending power into the public electricity grid. However, the preferred method is to get the energy meter readings directly from the MQTT broker, if this is possible. Enter the MQTT topic used by the energy meter reading.

See README.md for more configuraton parameters.

## First run

Open the AppDaemon web interface on port 5050. Go to the logs page, select the energyrouter_log.

It should say that Energy Router is disabled.

In energy_router.yaml, set the `go` parameter to 1 and save the file.

The Energy Router should start (watch the log file). There should be a couple of lines in the log:

- Energy Router start,

- a line about RouterMode (if you already configured the H.A. entities to control the router),

- a line about gridpower, with the current value,

- a line about the dimmer being online or offline (only if the dimmer already connected at least once to the MQTT broker).

When all the pieces of the project are put together, all these lines should show up every time you restart Energy Router.

That's it.
