"""Parsers and fallbacks for live feeds — sample payloads only, no network."""
from datetime import datetime, timezone

from app import agents, five11, live, weather

NOW = datetime(2026, 10, 23, 21, 0, tzinfo=timezone.utc)

SIRI = {"ServiceDelivery": {"StopMonitoringDelivery": {"MonitoredStopVisit": [
    {"MonitoredVehicleJourney": {"LineRef": "N", "DirectionRef": "OB", "DestinationRef": "999",
                                 "DestinationName": "Ocean Beach",
                                 "MonitoredCall": {"ExpectedArrivalTime": "2026-10-23T21:07:00Z"}}},
    {"MonitoredVehicleJourney": {"LineRef": "N", "DirectionRef": "OB", "DestinationRef": "999",
                                 "MonitoredCall": {"AimedArrivalTime": "2026-10-23T21:03:00Z"}}},
    {"MonitoredVehicleJourney": {"LineRef": "N",
                                 "MonitoredCall": {"ExpectedArrivalTime": "2026-10-23T20:50:00Z"}}},
]}}}


def test_stop_monitoring_sorted_skips_departed_and_marks_realtime():
    visits = five11.parse_stop_monitoring(SIRI, now=NOW)
    assert [v["minutes"] for v in visits] == [3.0, 7.0]
    assert visits[0]["realtime"] is False and visits[1]["realtime"] is True


def test_stop_monitoring_accepts_list_delivery_and_single_visit():
    payload = {"ServiceDelivery": {"StopMonitoringDelivery": [{"MonitoredStopVisit": {
        "MonitoredVehicleJourney": {"LineRef": "T",
                                    "MonitoredCall": {"ExpectedArrivalTime": "2026-10-23T21:02:00Z"}}}}]}}
    assert five11.parse_stop_monitoring(payload, now=NOW)[0]["line"] == "T"


def test_parse_stops_skips_bad_rows():
    payload = {"Contents": {"dataObjects": {"ScheduledStopPoint": [
        {"id": 15731, "Name": "Powell", "Location": {"Latitude": "37.78", "Longitude": "-122.40"}},
        {"id": "x", "Name": "broken"}]}}}
    assert five11.parse_stops(payload) == [{"code": "15731", "name": "Powell", "lat": 37.78, "lon": -122.40}]


def test_alerts_parser_is_case_insensitive():
    payload = {"Entities": [{"Alert": {"InformedEntities": [{"AgencyId": "SF", "RouteId": "N"}],
                                       "HeaderText": {"Translations": [{"Text": "N shuttle buses"}]}}},
                            {"alert": {"informed_entity": [{"route_id": "F"}],
                                       "header_text": {"translation": [{"text": "F delays"}]}}}]}
    assert five11.parse_alerts(payload) == {"N": ["N shuttle buses"], "F": ["F delays"]}


def test_no_key_means_no_lookups(monkeypatch):
    monkeypatch.delenv("FIVE11_API_KEY", raising=False)
    monkeypatch.delenv("API_511_KEY", raising=False)
    assert five11.next_arrival("muni", "N", (37.78, -122.40), (37.76, -122.50)) is None
    assert five11.alerts("muni") == {}


def test_budget_stops_after_limit():
    b = live.Budget(2)
    assert b.take() and b.take() and not b.take()


def test_weather_classification():
    assert weather.classify("Light Rain", 10) == "rain"
    assert weather.classify("Sunny", 60) == "rain"
    assert weather.classify("Patchy Fog", 0) == "fog"
    assert weather.classify("Mostly Clear", 5) == "clear"
    assert weather.wind_mph("10 to 25 mph") == 25


def test_live_weather_failure_falls_back_to_clear(monkeypatch):
    monkeypatch.setenv("HOPPER_OFFLINE", "1")
    req = {**agents.DEFAULTS, "origin": "ferry_building", "destination": "coit_tower",
           "hour": 12, "weather": "live"}
    trace = agents.Trace()
    out = agents.context_agent(req, trace)
    assert out["weather"] == "clear"
    assert "unavailable" in trace.steps[0]["detail"]
