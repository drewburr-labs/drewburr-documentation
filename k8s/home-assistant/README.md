# Home Assistant

Home Assistant deployment with Prometheus metrics export enabled for Ecobee thermostat monitoring.

## Features

- Persistent storage (5Gi ZFS NVMe-oF)
- Ingress with TLS at homeassistant.drewburr.com
- Prometheus metrics export enabled via built-in integration
- ServiceMonitor for automatic Prometheus scraping
- Configuration managed via persistence volume

## Setup

### 1. Deploy Home Assistant

```bash
helm dependency update
helm upgrade --install home-assistant . -n home-assistant --create-namespace
```

### 2. Add Ecobee Integration

After Home Assistant starts:

1. Access Home Assistant UI at homeassistant.drewburr.com
2. Go to Settings → Devices & Services → Add Integration
3. Search for "Ecobee"
4. Follow OAuth flow to connect your Ecobee account (no API key needed!)

### 3. Create Prometheus Token

For Prometheus to scrape metrics:

1. In Home Assistant: Profile → Security → Long-Lived Access Tokens
2. Create a new token named "Prometheus"
3. Create the Kubernetes secret:

```bash
kubectl create secret generic home-assistant-prometheus-token \
  -n home-assistant \
  --from-literal=token='YOUR_LONG_LIVED_TOKEN'
```

### 4. Verify Metrics

Check metrics endpoint:

```bash
kubectl port-forward -n home-assistant svc/home-assistant 8123:8123
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8123/api/prometheus
```

## Prometheus Metrics

Once Ecobee is connected, available metrics include:

- `hass_sensor_temperature_c{entity="sensor.living_room_temperature"}`
- `hass_sensor_humidity_percent{entity="sensor.living_room_humidity"}`
- `hass_climate_current_temperature_c{entity="climate.ecobee"}`
- `hass_binary_sensor_state{entity="binary_sensor.ecobee_occupancy"}`

## Grafana Dashboard

Import Grafana dashboard for Home Assistant metrics:

- Dashboard ID: 11133 (Home Assistant Statistics)
